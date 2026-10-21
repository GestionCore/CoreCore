"""
Herramientas de SOLO LECTURA del asistente de IA (asistente.py).

La IA nunca toca la base ni escribe SQL: cuando necesita un dato pide una de estas funciones por su nombre y recibe un resultado ACOTADO (períodos de hasta 92 días, rankings de 10, sin nombres,
direcciones ni mensajes de compradores). Cada una abre `db.conexion_usuario(usuario_id, cuenta_id)` —o sea, con RLS— y además filtra por `cuenta_id` en la consulta: aunque una política
fallara, una cuenta no podría leer los datos de otra. Ninguna escribe nada. Todo lo que devuelven es DATO, no instrucciones (el prompt del asistente se lo dice al modelo).
"""
import json
import re
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import analisis_stock
import cache_db
import calidad as calidad_mod
import catalogo_ganar as catalogo_mod
import chat_ia
import cobros as cobros_mod
import costos as costos_mod
import dashboard as dashboard_mod
import db
import despacho as despacho_mod
import despacho_corte
import dolar as dolar_mod
import embudo_conversion as embudo_mod
import espia_competencia
import facturacion as facturacion_mod
import fiscal
import flex as flex_mod
import historial_precios as historial_mod
import logros as logros_mod
import mercado as mercado_mod
import metricas
import monotributo as monotributo_mod
import nav_config
import opiniones as opiniones_mod
import precios as precios_mod
import promociones as promociones_mod
import publicidad as publicidad_mod
import reputacion as reputacion_mod
import salud_cuenta
import tendencias as tendencias_mod
import tiempo_respuesta as tiempo_respuesta_mod
from auth import token_manager
from utils import SQL_RECLAMO_AFECTA, hoy_argentina, limpiar_titulo_modelo, prorratear_mensual, rotulo_variante, sql_momento_argentina, sql_variante_de_venta

MAX_DIAS = 92
DIAS_POR_DEFECTO = 30
MAX_PALABRAS_DE_BUSQUEDA = 6
MAX_LARGO_DE_BUSQUEDA = 80
MAX_MODELOS_EN_PRODUCTO = 3
MENSAJE_DESCONECTADA = "La cuenta de Mercado Libre está desconectada: hay que volver a conectarla desde la página para calcular este dato."


class ErrorDeHerramienta(Exception):
    """Un pedido que no se puede atender; el texto se le devuelve al modelo (sin códigos ni datos técnicos) para que lo explique."""


class Contexto:
    def __init__(self, usuario_id, cuenta_id, hoy=None):
        self.usuario_id, self.cuenta_id, self.hoy = usuario_id, cuenta_id, hoy or hoy_argentina()


@contextmanager
def _conexion(ctx):
    """La conexión de la persona (con RLS) y de SOLO LECTURA: si una herramienta intentara escribir algo, Postgres mismo lo rechaza."""
    with db.conexion_usuario(ctx.usuario_id, ctx.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.close()
        yield conexion


def _token(ctx):
    try:
        return token_manager.asegurar_token_valido(ctx.cuenta_id)
    except token_manager.CuentaDesconectada:
        raise ErrorDeHerramienta(MENSAJE_DESCONECTADA)


def _fecha(valor, nombre):
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErrorDeHerramienta(f"«{nombre}» tiene que ser una fecha AAAA-MM-DD (por ejemplo 2026-10-01).")


def _periodo(ctx, desde=None, hasta=None, dias=None):
    """
    (desde, hasta, nota) como fechas. `dias` = «los últimos N días contando hoy» (1 = solo hoy): lo calcula el servidor, así «los últimos 30 días» da SIEMPRE las mismas fechas y las mismas cifras
    (cuando el modelo calculaba las fechas a mano, dos preguntas seguidas daban 14/09 y 15/09 como inicio). Sin datos: los últimos 30 días hasta hoy. Un período más largo que MAX_DIAS se acorta
    (y se avisa); uno al revés se da vuelta.
    """
    if dias not in (None, ""):
        try:
            cantidad = int(dias)
        except (TypeError, ValueError):
            raise ErrorDeHerramienta("«dias» tiene que ser un número entero (por ejemplo 7 o 30).")
        if cantidad < 1:
            raise ErrorDeHerramienta("«dias» tiene que ser 1 o más.")
        nota = f"El período se acortó a los últimos {MAX_DIAS} días (el máximo)." if cantidad > MAX_DIAS else None
        cantidad = min(cantidad, MAX_DIAS)
        return ctx.hoy - timedelta(days=cantidad - 1), ctx.hoy, nota
    hasta = _fecha(hasta, "hasta") or ctx.hoy
    desde = _fecha(desde, "desde") or (hasta - timedelta(days=DIAS_POR_DEFECTO - 1))
    if desde > hasta:
        desde, hasta = hasta, desde
    nota = None
    if (hasta - desde).days + 1 > MAX_DIAS:
        desde = hasta - timedelta(days=MAX_DIAS - 1)
        nota = f"El período se acortó a los últimos {MAX_DIAS} días (el máximo)."
    return desde, hasta, nota


def _plata(valor):
    return round(float(valor or 0), 2)


def _con_nota(datos, nota):
    if nota:
        datos["nota"] = nota
    return datos


# ── Ventas ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _ventas(ctx, desde=None, hasta=None, agrupar="total", dias=None):
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    agrupar = agrupar if agrupar in ("total", "dia", "modelo", "variante", "provincia", "horario", "logistica") else "total"
    donde, parametros = "v.cuenta_id = %s AND v.origen = 'meli' AND v.fecha_venta BETWEEN %s AND %s", (ctx.cuenta_id, desde, hasta)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute(f"SELECT COALESCE(SUM(v.precio_venta * v.cantidad), 0), COALESCE(SUM(v.cantidad), 0), COUNT(DISTINCT v.id_orden) FROM ventas v WHERE {donde}", parametros)
        facturado, unidades, ordenes = cursor.fetchone()
        datos = {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "facturado": _plata(facturado), "unidades": int(unidades), "ordenes": int(ordenes),
                 "origen": "ventas netas de Mercado Libre (sin canceladas ni devueltas); pantalla: Ganancia Real"}
        if agrupar == "dia":
            cursor.execute(f"SELECT v.fecha_venta, COALESCE(SUM(v.precio_venta * v.cantidad), 0), COALESCE(SUM(v.cantidad), 0) FROM ventas v WHERE {donde} GROUP BY 1 ORDER BY 1", parametros)
            datos["por_dia"] = [{"fecha": f.isoformat(), "facturado": _plata(t), "unidades": int(u)} for f, t, u in cursor.fetchall()]
        elif agrupar == "modelo":
            cursor.execute(
                f"""SELECT COALESCE(v.titulo, ''), v.id_meli, SUM(v.cantidad), SUM(v.precio_venta * v.cantidad), NULL, true, MAX(NULLIF(pv.talle, 'Único'))
                    FROM ventas v LEFT JOIN productos_variantes pv ON pv.id_variante = {sql_variante_de_venta("v")} AND pv.cuenta_id = v.cuenta_id
                    WHERE {donde} GROUP BY v.titulo, v.id_meli""", parametros)
            datos["por_modelo"] = [{"modelo": m["nombre"], "unidades": m["unidades"], "facturado": _plata(m["facturado"]), "pct_del_total": m["pct"]}
                                   for m in dashboard_mod.top_modelos(cursor.fetchall(), maximo=10)]
        elif agrupar == "variante":
            cursor.execute(
                f"""SELECT v.titulo, SUM(v.cantidad), SUM(v.precio_venta * v.cantidad), MAX(pv.talle), MAX(pv.etiqueta)
                    FROM ventas v LEFT JOIN productos_variantes pv ON pv.id_variante = {sql_variante_de_venta("v")} AND pv.cuenta_id = v.cuenta_id
                    WHERE {donde} GROUP BY v.titulo, {sql_variante_de_venta("v")}""", parametros)
            juntas = {}
            for titulo, cantidad, total, talle, etiqueta in cursor.fetchall():
                clave = (limpiar_titulo_modelo(titulo, talle) or titulo or "Sin nombre", rotulo_variante(etiqueta, talle))
                u, f = juntas.get(clave, (0, 0.0))
                juntas[clave] = (u + int(cantidad or 0), f + float(total or 0))
            ordenadas = sorted(juntas.items(), key=lambda kv: -kv[1][1])[:15]
            datos["por_variante"] = [{"modelo": m, "variante": None if v == "Única" else v, "unidades": u, "facturado": _plata(f)} for (m, v), (u, f) in ordenadas]
        elif agrupar == "provincia":
            cursor.execute(f"""SELECT v.provincia, COUNT(DISTINCT v.id_orden), COALESCE(SUM(v.precio_venta * v.cantidad), 0) FROM ventas v
                               WHERE {donde} AND v.provincia IS NOT NULL AND v.eliminado_en IS NULL GROUP BY v.provincia ORDER BY 3 DESC""", parametros)
            filas = cursor.fetchall()
            con_provincia = sum(float(f[2]) for f in filas)
            datos["por_provincia"] = [{"provincia": p, "ordenes": int(o), "facturado": _plata(f), "pct_de_lo_facturado_con_provincia": round(float(f) / con_provincia * 100, 1) if con_provincia else 0} for p, o, f in filas[:10]]
            datos["aclaracion"] = "La provincia sale del envío: las ventas sin ese dato (manuales o muy viejas) no entran en el ranking."
        elif agrupar == "horario":
            momento = sql_momento_argentina("v")
            cursor.execute(f"""SELECT EXTRACT(ISODOW FROM {momento})::int, EXTRACT(HOUR FROM {momento})::int, COUNT(DISTINCT v.id_orden) FROM ventas v
                               WHERE {donde} AND v.hora_venta IS NOT NULL AND v.eliminado_en IS NULL GROUP BY 1, 2""", parametros)
            datos["cuando_compran"] = _cuando_compran(cursor.fetchall())
        elif agrupar == "logistica":
            cursor.execute(f"""SELECT COALESCE(NULLIF(v.tipo_logistica, ''), 'sin_dato'), COUNT(DISTINCT v.id_orden), COALESCE(SUM(v.cantidad), 0), COALESCE(SUM(v.precio_venta * v.cantidad), 0), COALESCE(SUM(v.costo_envio), 0)
                               FROM ventas v WHERE {donde} AND v.eliminado_en IS NULL GROUP BY 1""", parametros)
            datos["por_modalidad_de_envio"] = _resumen_de_logistica(cursor.fetchall())
            sin_costo, total_flex = _flex_sin_costo(cursor, ctx, desde, hasta)
            datos["envios_flex_del_periodo_sin_costo_de_entrega"] = sin_costo
            datos["aclaracion"] = ("El costo de envío es lo que cuesta de verdad cada modalidad (en Flex, lo que cobra tu logística según tus precios por zona). "
                                   + (f"{sin_costo} de {total_flex} envíos Flex del período todavía no tienen costo asignado: figuran en 0 hasta que se cargue en la pantalla Costos (entrega Flex)." if sin_costo else ""))
    return _con_nota(datos, nota)


def _calcular_ganancia(ctx, desde, hasta):
    """El mismo cálculo de la pantalla Ganancia Real (metricas.calcular_ganancia_real) para la cuenta de la persona."""
    return metricas.calcular_ganancia_real(ctx.usuario_id, ctx.cuenta_id, _token(ctx), desde.isoformat(), hasta.isoformat())


def _flex_sin_costo(cursor, ctx, desde, hasta):
    """(envíos Flex del período sin costo de entrega asignado, envíos Flex del período): lo mismo que avisa la pantalla Ganancia Real."""
    r = flex_mod.resumen_periodo(cursor, ctx.cuenta_id, desde.isoformat(), hasta.isoformat())
    return r["sin_zona"], r["ordenes"]


def _texto_flex(sin_costo, total):
    return (f"{sin_costo} de {total} envíos Flex del período todavía no tienen costo de entrega asignado: ese costo no está en la ganancia, que puede ser menor. "
            "Se carga en la pantalla Costos (entrega Flex).")


def _desglose_de_ganancia(ctx, resultado, desde, hasta):
    raw = resultado["resumen"]["raw"]
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cobertura = costos_mod.cobertura_de_costos(cursor, desde.isoformat(), hasta.isoformat())
        flex_sin_costo, flex_total = _flex_sin_costo(cursor, ctx, desde, hasta)
    facturado = float(raw.get("facturado") or 0)
    ganancia = float(raw.get("ganancia_neta") or 0)
    datos = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "facturado": _plata(facturado), "cargos_de_mercado_libre": _plata(raw.get("comision")), "envios": _plata(raw.get("envios")),
        "publicidad": _plata(raw.get("costo_ads")), "costo_de_fabricacion": _plata(raw.get("costo_fabricacion")), "cargos_mensuales_de_mercado_libre": _plata(raw.get("cargos_fuera_de_ventas")),
        "ganancia_neta_real": _plata(ganancia), "margen_pct": round(ganancia / facturado * 100, 1) if facturado > 0 else None,
        "ventas_sin_costo_de_fabricacion_cargado_pct": cobertura["pct_sin_costo"], "origen": "pantalla Ganancia Real",
    }
    avisos = []
    datos["envios_flex_del_periodo_sin_costo_de_entrega"] = flex_sin_costo
    if cobertura["pct_sin_costo"] > 0:
        avisos.append("Parte de lo vendido no tiene costo de fabricación cargado: la ganancia real puede ser menor. Se carga en la pantalla Costos.")
    if flex_sin_costo:
        avisos.append(_texto_flex(flex_sin_costo, flex_total))
    if resultado.get("ads_incompleto"):
        avisos.append("Mercado Libre no devolvió todo el gasto en publicidad: el costo de publicidad puede estar incompleto.")
    if avisos:
        datos["aviso"] = " ".join(avisos)
    return datos


def _ganancia_real(ctx, desde=None, hasta=None, dias=None):
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    return _con_nota(_desglose_de_ganancia(ctx, _calcular_ganancia(ctx, desde, hasta), desde, hasta), nota)


def _ganancia_por_modelo(ctx, desde=None, hasta=None, dias=None):
    """Qué modelos dejan plata y cuáles no: la tabla «por modelo» de Ganancia Real (todas las variantes de un modelo juntas, promedio ponderado)."""
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    resultado = _calcular_ganancia(ctx, desde, hasta)
    with _conexion(ctx) as conexion:
        flex_sin_costo, flex_total = _flex_sin_costo(conexion.cursor(), ctx, desde, hasta)
    modelos = []
    for c in resultado.get("consolidados") or []:
        r = c["raw"]
        facturado, neto = float(r["total_facturado"] or 0), float(r["neto_total"] or 0)
        modelos.append({"modelo": c["titulo"], "unidades": int(c["unidades"]), "facturado": _plata(facturado), "ganancia_neta": _plata(neto), "ganancia_por_unidad": _plata(r["neto_u"]),
                        "margen_pct": round(neto / facturado * 100, 1) if facturado > 0 else None, "sin_costo_cargado": float(r["costo_u"] or 0) <= 0})
    datos = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "modelos_vendidos": len(modelos),
        "los_que_mas_dejan": sorted(modelos, key=lambda m: -m["ganancia_neta"])[:8],
        "los_que_pierden_plata": sorted((m for m in modelos if m["ganancia_neta"] < 0), key=lambda m: m["ganancia_neta"])[:8],
        "modelos_sin_costo_de_fabricacion_cargado": [m["modelo"] for m in modelos if m["sin_costo_cargado"]][:8],
        "aclaracion": "La ganancia de cada modelo ya descuenta cargos de Mercado Libre, envíos, publicidad y costo de fabricación, pero no los cargos mensuales de Mercado Libre (se descuentan solo del total): por eso la suma de los modelos puede ser algo mayor que la ganancia neta real.",
        "origen": "pantalla Ganancia Real (tabla por modelo)",
    }
    if datos["modelos_sin_costo_de_fabricacion_cargado"]:
        datos["aviso"] = "Los modelos sin costo de fabricación cargado muestran una ganancia más alta que la real. El costo se carga en la pantalla Costos."
    if flex_sin_costo:
        datos["aviso_flex"] = _texto_flex(flex_sin_costo, flex_total)
    if resultado.get("ads_incompleto"):
        datos["aviso_publicidad"] = "Mercado Libre no devolvió todo el gasto en publicidad: la ganancia de cada modelo puede estar algo inflada."
    return _con_nota(datos, nota)


# ── Stock, posventa, calidad, mercado, cobros, pendientes, costos ──────────────────────────────────────────────────────────────────────────

def _stock(ctx):
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(stock_propio), 0), COALESCE(SUM(stock_full), 0) FROM productos_variantes WHERE cuenta_id = %s", (ctx.cuenta_id,))
        variantes, propio, full = cursor.fetchone()
        cursor.execute(
            """SELECT COUNT(*) FROM productos_variantes v JOIN productos_padre p ON p.id = v.id_padre
               WHERE p.cuenta_id = %s AND p.estado = 'active' AND COALESCE(v.stock_propio, 0) + COALESCE(v.stock_full, 0) = 0""", (ctx.cuenta_id,))
        sin_stock = cursor.fetchone()[0]
        en_riesgo = analisis_stock.obtener_variantes_en_riesgo(cursor)
        clave = analisis_stock.evaluar_cobertura_variantes(cursor)
    return {
        "variantes_publicadas": int(variantes), "unidades_en_deposito_propio": int(propio), "unidades_en_full": int(full), "variantes_activas_sin_stock": int(sin_stock),
        "se_agotan_pronto": [{"producto": v["titulo"], "variante": None if v["variante"] == "Única" else v["variante"], "unidades_restantes": v["stock_total"], "dias_que_alcanzan": v["dias_restantes"],
                              "hay_que_pedir_ya": bool(v["pedir_ya"])} for v in en_riesgo[:10]],
        "variantes_clave_sin_stock": [{"modelo": c["modelo"], "variante": None if c["variante"] == "Única" else c["variante"], "aporta_pct_de_las_ventas_del_modelo": c["aporta_pct"]} for c in clave[:10]],
        "origen": "pantalla Stock (ritmo de venta de los últimos 14 días; variantes clave: últimos 30)",
    }


def _posventa(ctx):
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            f"""SELECT COUNT(*) FILTER (WHERE tipo = 'claim' AND {SQL_RECLAMO_AFECTA}), COUNT(*) FILTER (WHERE tipo = 'return' OR (tipo = 'claim' AND NOT {SQL_RECLAMO_AFECTA})),
                       COALESCE(SUM(monto_retenido), 0)
                FROM incidencias_posventa WHERE cuenta_id = %s AND estado NOT IN ('closed', 'resolved')""", (ctx.cuenta_id,))
        reclamos, otras, retenido = cursor.fetchone()
        cursor.execute("SELECT COUNT(*), MIN(fecha_pregunta) FROM preguntas_pendientes WHERE cuenta_id = %s AND estado = 'pendiente'", (ctx.cuenta_id,))
        preguntas, mas_vieja = cursor.fetchone()
    horas = None
    if mas_vieja is not None:
        referencia = datetime.now(mas_vieja.tzinfo) if mas_vieja.tzinfo else datetime.now(timezone.utc).replace(tzinfo=None)
        horas = max(0, round((referencia - mas_vieja).total_seconds() / 3600))
    return {
        "reclamos_abiertos_que_afectan_la_reputacion": int(reclamos), "devoluciones_y_reclamos_sin_impacto_en_la_reputacion": int(otras), "dinero_retenido_por_reclamos": _plata(retenido),
        "preguntas_sin_responder": int(preguntas), "horas_de_la_pregunta_mas_vieja": horas, "origen": "pantalla Día a día (Preguntas y Pendientes) y Cobros",
    }


def _calidad(ctx):
    with _conexion(ctx) as conexion:
        d = calidad_mod.obtener_datos(conexion.cursor(), ctx.cuenta_id)
    return {
        "publicaciones_activas": d["total_activas"], "puntaje_promedio_de_mercado_libre": d["promedio"], "publicaciones_al_100": d["al_cien"], "publicaciones_con_mejoras_pendientes": len(d["con_mejoras"]),
        "mejoras_mas_repetidas": [{"mejora": a["texto"], "publicaciones": a["cantidad"]} for a in d["top_acciones"]],
        "visitas_14_dias": d["total_visitas"], "variacion_de_visitas_pct": d["tendencia_visitas"], "conversion_pct": d["conversion"],
        "publicaciones_que_pierden_visitas": [{"titulo": i["titulo"], "variacion_pct": i["tendencia"]} for i in d["perdiendo_visitas"][:5]],
        "origen": "pantalla Calidad (datos de Mercado Libre guardados en CoreLux)",
    }


def _mercado(ctx):
    with _conexion(ctx) as conexion:
        d = mercado_mod.armar_pantalla(conexion.cursor(), ctx.cuenta_id)
    ficha = d["ficha"]
    todas = d["busquedas_tuyas"]
    sin_cubrir = [b for b in todas if not b["tus_publicaciones"]]
    datos = {
        "dias_de_historia": d["cobertura"]["dias"], "categorias_seguidas": d["cobertura"]["categorias"],
        # Las cuentas las hace el servidor: el modelo no cuenta ni compara a ojo
        "resumen": {"busquedas_en_alza_en_tus_categorias": len(todas), "que_ya_cubris_con_alguna_publicacion": len(todas) - len(sin_cubrir), "sin_ninguna_publicacion_tuya": len(sin_cubrir),
                    "las_mejor_posicionadas_que_no_cubris": [{"busqueda": b["texto"][:80], "puesto": b["posicion"], "categoria": b["categoria_nombre"]} for b in sin_cubrir[:3]]},
        "busquedas_en_alza_en_tus_categorias": [
            {"busqueda": b["texto"][:80], "categoria": b["categoria_nombre"], "puesto": b["posicion"], "movimiento": b["movimiento"][1] if b["movimiento"] else None, "tus_publicaciones_con_esa_busqueda": b["tus_publicaciones"],
             "dias_seguidos_en_la_lista": b["racha"], "mejor_puesto_alcanzado": b["mejor_posicion"], "que_entiende_mercado_libre": b["entiende"]}
            for b in todas[:12]],
        "categorias_sin_relevar_todavia": [c["nombre"] for c in d["sin_relevar"]][:5],
        "aclaracion": "Mercado Libre informa el puesto de cada búsqueda en alza y cuántas publicaciones tiene cada categoría; no informa el volumen de búsquedas ni las ventas de otros vendedores.", "origen": "pantalla Mercado",
    }
    if ficha:
        muestra = ficha["muestra"] if ficha["muestra"] and not ficha["muestra"]["vacia"] else None
        datos["categoria_destacada"] = {
            "nombre": ficha["nombre"], "publicaciones_en_el_mercado": ficha["publicaciones"], "variacion_7_dias_pct": ficha["variacion_7"]["pct"] if ficha["variacion_7"] else None,
            "variacion_30_dias_pct": ficha["variacion_30"]["pct"] if ficha["variacion_30"] else None,
            "precio_mediano": float(muestra["precio_p50"]) if muestra and muestra["precio_p50"] else None,
            "rango_de_precios_habitual": [float(muestra["precio_p25"]), float(muestra["precio_p75"])] if muestra and muestra["precio_p25"] and muestra["precio_p75"] else None,
            "ofertas_con_full_pct": float(muestra["pct_full"]) if muestra and muestra["pct_full"] is not None else None,
            "ofertas_con_envio_gratis_pct": float(muestra["pct_envio_gratis"]) if muestra and muestra["pct_envio_gratis"] is not None else None,
            "oferta": muestra["concentracion"][1] if muestra and muestra["concentracion"] else None,
            "la_muestra_es_de": "esa categoría" if muestra and muestra.get("alcance") != "dominio" else ("todo el rubro (la categoría tiene pocas ofertas de catálogo)" if muestra else None)}
    return datos


def _tendencias(ctx):
    """Lo que muestra la pantalla Tendencias, SOLO LEYENDO: las búsquedas en tendencia de las categorías donde vende la persona, cuáles ya están en algún título suyo, las fechas comerciales que vienen y
    cómo se mueve la oferta de las categorías que sigue. No guarda nada (la pantalla sí guarda seguimientos y la caché; acá una transacción de solo lectura lo impediría)."""
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        categorias = tendencias_mod.categorias_del_catalogo(cursor)
        if not categorias:
            return {"hay_tendencias": False, "mensaje": "Todavía no hay categorías guardadas de las publicaciones de esta cuenta, así que no se pueden armar tendencias de su rubro.", "origen": "pantalla Tendencias"}
        cursor.execute("SELECT category_id, nombre FROM mercado_categorias WHERE category_id = ANY(%s)", ([c for c, _ in categorias],))
        nombres = dict(cursor.fetchall())
        hit, guardado = cache_db.leer(cursor, ctx.cuenta_id, tendencias_mod.CLAVE_TENDENCIAS, ",".join(c for c, _ in categorias), tendencias_mod.TTL_TENDENCIAS_SEGUNDOS, ttl_fallido=600)
    lista = (guardado or {}).get("lista") if hit else None
    if not lista:
        token = _token(ctx)                                                       # la caché de la pantalla no sirve (venció o nunca se abrió): se pide a Mercado Libre, sin guardar nada
        lista = tendencias_mod.mezclar_tendencias([(cid, tendencias_mod.obtener_tendencias(token, category_id=cid)) for cid, _ in categorias])
    if not lista:
        return {"hay_tendencias": False, "mensaje": "Mercado Libre no devolvió tendencias ahora mismo para las categorías de esta cuenta.", "origen": "pantalla Tendencias"}

    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        tendencias_mod.cruzar_tendencias_con_catalogo(lista, cursor)             # marca en cada una si ya está en algún título (no escribe)
        seguimientos = tendencias_mod.listar_seguimientos_con_historial(cursor, ctx.cuenta_id)
    sin_cubrir = [t for t in lista if not t.get("cubierta")]
    return {
        "hay_tendencias": True,
        "categorias_analizadas": [{"categoria": nombres.get(cid) or cid, "tus_publicaciones_activas": cantidad} for cid, cantidad in categorias],
        "resumen": {"busquedas_en_tendencia": len(lista), "ya_estan_en_algun_titulo_tuyo": len(lista) - len(sin_cubrir), "sin_cubrir": len(sin_cubrir),
                    "las_mejor_posicionadas_sin_cubrir": [{"busqueda": str(t.get("keyword") or "")[:80], "puesto": t.get("posicion")} for t in sin_cubrir[:3]]},
        "busquedas_en_tendencia": [{"puesto": t.get("posicion"), "busqueda": str(t.get("keyword") or "")[:80], "categoria": nombres.get(t.get("categoria_id")) or t.get("categoria_id"), "ya_esta_en_un_titulo_tuyo": bool(t.get("cubierta"))} for t in lista[:12]],
        "fechas_comerciales_proximas": [{"fecha": e["nombre"], "en_dias": e["dias_faltantes"], "rubros_que_se_mueven": e["categoria_sugerida"]} for e in tendencias_mod.obtener_calendario_estacional()[:3]],
        "categorias_que_sigue": [{"categoria": str(s["etiqueta"] or s["valor"])[:80], "variacion_de_la_oferta_pct": s["tendencia_pct"], "dias_de_historia": len(s["serie"])} for s in seguimientos if s["tipo"] == "categoria" and s["tiene_historial_suficiente"]][:5],
        "aclaracion": "Mercado Libre informa qué búsquedas están en tendencia y su puesto de hoy; no informa cuántas veces se busca cada una. «Ya está en un título tuyo» significa que la palabra aparece en el título de alguna de sus publicaciones activas.",
        "origen": "pantalla Tendencias",
    }


def _cobros(ctx):
    with _conexion(ctx) as conexion:
        d = cobros_mod.obtener_datos(conexion.cursor(), ctx.cuenta_id, ctx.hoy, None)
    proximo = d["proximo"]
    return {
        "se_acredita_hoy": _plata(d["hoy"]), "se_acredita_manana": _plata(d["manana"]), "se_acredita_en_7_dias": _plata(d["semana"]), "total_por_acreditar": _plata(d["total"]),
        "proxima_acreditacion": {"fecha": proximo["fecha"].isoformat(), "monto": _plata(proximo["monto"])} if proximo else None,
        "acreditado_recientemente": _plata(d["acreditado"]), "dias_de_lo_acreditado": d["dias_acreditado"], "dinero_retenido_por_reclamos": _plata(d["retenido_total"]), "origen": "pantalla Cobros",
    }


def _pendientes(ctx):
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        misiones = logros_mod._detectar_misiones_base(cursor, ctx.cuenta_id)
        salud = salud_cuenta.calcular_score_salud(cursor)
    return {
        "salud_de_la_cuenta": {"puntaje_de_100": salud["score"], "estado": salud["etiqueta"], "por_que": salud["detalle"][:6]},
        "pendientes": [{"que": m["titulo"], "detalle": m["descripcion"], "prioridad": m["prioridad"], "pantalla": m["link"]} for m in misiones[:8]],
        "origen": "pantalla Día a día (Pendientes)",
    }


def _costos(ctx):
    desde, hasta, _ = _periodo(ctx)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cobertura = costos_mod.cobertura_de_costos(cursor, desde.isoformat(), hasta.isoformat())
        cursor.execute("SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %s AND estado = 'active' AND COALESCE(precio_costo, 0) = 0", (ctx.cuenta_id,))
        sin_costo = cursor.fetchone()[0]
        cotizacion = dolar_mod.cotizacion_activa(cursor, ctx.cuenta_id)
    return {
        "publicaciones_activas_sin_costo_de_fabricacion": int(sin_costo), "ultimos_30_dias": {"facturado": _plata(cobertura["facturado"]), "facturado_sin_costo_cargado": _plata(cobertura["sin_costo"]),
                                                                                           "pct_sin_costo": cobertura["pct_sin_costo"]},
        "dolar_para_los_costos": {"valor": cotizacion["valor"], "modo": cotizacion["modo"]}, "origen": "pantalla Costos",
    }


# ── Publicidad, precios, comparación entre períodos, reputación, Monotributo y búsqueda de un producto ──────────────────────────────────────

def _publicidad(ctx, desde=None, hasta=None, dias=None):
    """Product Ads: lo mismo que la pantalla Publicidad (gasto, ventas que trajo, retorno contra el punto de equilibrio, cada campaña, publicaciones que gastan sin vender)."""
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    datos = publicidad_mod.calcular_datos_publicidad(ctx.usuario_id, ctx.cuenta_id, _token(ctx), desde.isoformat(), hasta.isoformat())
    if datos is None:
        return {"usa_product_ads": False, "mensaje": "Esta cuenta no tiene Product Ads (la publicidad de Mercado Libre) activado, o todavía no se pudo leer. No hay gasto en publicidad para analizar.", "origen": "pantalla Publicidad"}
    if datos.get("incompleto"):
        raise ErrorDeHerramienta("Mercado Libre no devolvió los datos de publicidad ahora mismo: no puedo decir cuánto se gastó. Probá de nuevo en un rato.")
    campanas = datos["campanas"]
    gasto = sum(float(c["costo"] or 0) for c in campanas)
    ventas = sum(float(c["ventas_atribuidas"] or 0) for c in campanas)
    sin_ventas = [i for i in datos["items_ads"] if i["sin_ventas"]]
    resultado = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "usa_product_ads": True, "gastaste": _plata(gasto), "ventas_que_trajo_la_publicidad": _plata(ventas), "unidades_vendidas_con_publicidad": int(datos["unidades_total"] or 0),
        "retorno_roas": datos["roas_general"], "roas_de_equilibrio": datos["roas_equilibrio"], "la_publicidad_te_deja_ganancia": datos["te_deja_ganancia"],
        "veces_por_encima_del_equilibrio": round(datos["roas_general"] / datos["roas_equilibrio"], 1) if datos["roas_general"] is not None and datos["roas_equilibrio"] else None,
        "acos_pct": datos["acos_general"], "peso_de_la_publicidad_sobre_lo_facturado_pct": datos["tacos"], "costo_por_clic": datos["cpc"], "costo_por_venta": datos["cpa"],
        "porcentaje_de_lo_facturado_que_vino_de_anuncios": datos["pct_origen_pagado"],
        "contra_el_periodo_anterior": {"variacion_del_gasto_pct": datos["anterior"]["costo_pct"], "variacion_de_las_ventas_pct": datos["anterior"]["ventas_pct"], "roas_anterior": datos["anterior"]["roas"]} if datos.get("anterior") else None,
        "campanas": [{"campana": c["nombre"], "estado": c["estado"], "gastaste": _plata(c["costo"]), "ventas": _plata(c["ventas_atribuidas"]), "retorno_roas": c["roas"], "unidades": int(c["unidades"] or 0),
                      "presupuesto_diario": _plata(c["presupuesto"]) if c.get("presupuesto") else None, "uso_promedio_del_presupuesto_diario_pct": c["pct_presupuesto"], "sugerencia": c["recomendacion"]["texto"] if c.get("recomendacion") else None} for c in campanas[:8]],
        "publicaciones_que_gastaron_sin_vender": {"cantidad": len(sin_ventas), "gastaste_en_ellas": _plata(sum(i["costo"] for i in sin_ventas)), "las_que_mas_gastaron": [{"publicacion": i["titulo"], "gastaste": _plata(i["costo"])} for i in sin_ventas[:5]]},
        "aclaracion": "El retorno (ROAS) es lo que vendió la publicidad por cada $1 gastado. Para que no te coma la ganancia tiene que superar el ROAS de equilibrio, que sale del margen real del negocio sin contar la publicidad.",
        "origen": "pantalla Publicidad (Product Ads)",
    }
    return _con_nota(resultado, nota)


def _precios(ctx, margen_objetivo=None):
    """Precio mínimo (ganancia $0) y precio recomendado (con el margen objetivo) de cada publicación, calculados con la comisión y el envío reales de los últimos 90 días."""
    margen, _ = precios_mod.parametros(margen_objetivo, 0)
    with _conexion(ctx) as conexion:
        d = precios_mod.obtener_datos(conexion.cursor(), ctx.cuenta_id, margen, 0.0)

    def _fila(i):
        return {"publicacion": i["titulo"], "unidades_vendidas_90_dias": i["unidades"], "precio_actual": _plata(i["precio"]), "precio_minimo": i["minimo"], "precio_recomendado": i["recomendado"],
                "margen_actual_pct": i["margen_actual"], "perdida_mensual_estimada": _plata(i["perdida_mensual"]) if i["perdida_mensual"] else None, "pocas_ventas_para_confiar": bool(i["estimado"])}
    return {
        "margen_objetivo_pct": margen, "publicaciones_activas": d["total_activas"], "analizadas": len(d["items"]), "cubren_tu_margen": len(d["bien"]),
        "pierden_plata_al_precio_actual": {"cantidad": len(d["pierden"]), "perdida_mensual_total_estimada": _plata(d["perdida_mensual"]), "las_peores": [_fila(i) for i in d["pierden"][:8]]},
        "ganan_menos_que_tu_margen_objetivo": {"cantidad": len(d["justos"]), "las_de_mas_ventas": [_fila(i) for i in sorted(d["justos"], key=lambda i: -i["unidades"])[:8]]},
        "sin_costo_de_fabricacion_cargado": len(d["sin_costo"]), "sin_ventas_todavia": len(d["sin_ventas"]),
        "aclaracion": "Se calcula con los datos reales de cada publicación (comisión y envío de sus ventas de los últimos 90 días); las que no vendieron o no tienen costo cargado no se estiman. Los precios se pueden cambiar en la pantalla Precios.",
        "origen": "pantalla Precios",
    }


def _totales_de_ventas(cursor, desde, hasta):
    """Facturado, unidades y órdenes de un período: la misma suma con la que Ganancia Real se compara contra el período anterior (todas las ventas cargadas)."""
    cursor.execute("SELECT COALESCE(SUM(precio_venta * cantidad), 0), COALESCE(SUM(cantidad), 0), COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (desde, hasta))
    facturado, unidades, ordenes = cursor.fetchone()
    return {"facturado": float(facturado or 0), "unidades": int(unidades or 0), "ordenes": int(ordenes or 0)}


def _variacion(actual, anterior):
    actual, anterior = float(actual or 0), float(anterior or 0)
    return {"actual": _plata(actual), "anterior": _plata(anterior), "diferencia": _plata(actual - anterior), "variacion_pct": round((actual - anterior) / anterior * 100, 1) if anterior > 0 else None}


def _periodos_a_comparar(ctx, dias, modo):
    """((desde, hasta) actual, (desde, hasta) anterior, nota). `modo` «mes»: lo que va del mes contra el mismo tramo del mes anterior; si no, los últimos `dias` contra los `dias` anteriores."""
    if modo == "mes":
        inicio = ctx.hoy.replace(day=1)
        fin_anterior = inicio - timedelta(days=1)
        inicio_anterior = fin_anterior.replace(day=1)
        hasta_anterior = min(inicio_anterior + timedelta(days=(ctx.hoy - inicio).days), fin_anterior)
        return (inicio, ctx.hoy), (inicio_anterior, hasta_anterior), None
    desde, hasta, nota = _periodo(ctx, dias=dias if dias not in (None, "") else DIAS_POR_DEFECTO)
    largo = (hasta - desde).days + 1
    return (desde, hasta), (desde - timedelta(days=largo), desde - timedelta(days=1)), nota


def _comparar_periodos(ctx, dias=None, modo=None):
    """Este período contra el anterior de igual largo: ventas siempre, y ganancia real con sus costos cuando se puede calcular."""
    actual, anterior, nota = _periodos_a_comparar(ctx, dias, "mes" if modo == "mes" else "dias")
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        ahora, antes = _totales_de_ventas(cursor, *actual), _totales_de_ventas(cursor, *anterior)
        cobertura = costos_mod.cobertura_de_costos(cursor, actual[0].isoformat(), actual[1].isoformat())
        flex_sin_costo, flex_total = _flex_sin_costo(cursor, ctx, *actual)
    datos = {
        "periodo_actual": {"desde": actual[0].isoformat(), "hasta": actual[1].isoformat()}, "periodo_anterior": {"desde": anterior[0].isoformat(), "hasta": anterior[1].isoformat()},
        "facturado": _variacion(ahora["facturado"], antes["facturado"]), "unidades": _variacion(ahora["unidades"], antes["unidades"]), "ordenes": _variacion(ahora["ordenes"], antes["ordenes"]),
        "origen": "pantalla Ganancia Real (comparación con el período anterior)",
    }
    try:
        g_actual, g_anterior = _calcular_ganancia(ctx, *actual)["resumen"]["raw"], _calcular_ganancia(ctx, *anterior)["resumen"]["raw"]
        datos["ganancia_neta_real"] = _variacion(g_actual["ganancia_neta"], g_anterior["ganancia_neta"])

        def _margen(raw):
            return round(float(raw["ganancia_neta"]) / float(raw["facturado"]) * 100, 1) if float(raw["facturado"] or 0) > 0 else None
        m_actual, m_anterior = _margen(g_actual), _margen(g_anterior)
        datos["margen_pct"] = {"actual": m_actual, "anterior": m_anterior, "diferencia_en_puntos": round(m_actual - m_anterior, 1) if m_actual is not None and m_anterior is not None else None}
        datos["costos"] = {nombre: _variacion(g_actual[clave], g_anterior[clave]) for clave, nombre in
                           (("comision", "cargos_de_mercado_libre"), ("envios", "envios"), ("costo_ads", "publicidad"), ("costo_fabricacion", "costo_de_fabricacion"))}
        avisos = []
        if cobertura["pct_sin_costo"] > 0:
            avisos.append(f"El {cobertura['pct_sin_costo']}% de lo vendido en el período actual no tiene costo de fabricación cargado: la ganancia real puede ser menor.")
        if flex_sin_costo:
            avisos.append(_texto_flex(flex_sin_costo, flex_total))
        if avisos:
            datos["aviso"] = " ".join(avisos)
    except ErrorDeHerramienta as e:
        datos["ganancia_no_disponible"] = str(e)
    except Exception as e:
        print(f"[Asistente] ⚠️ No se pudo calcular la ganancia para comparar períodos: {type(e).__name__}: {e}")
        datos["ganancia_no_disponible"] = "No pude calcular la ganancia de los dos períodos ahora mismo; la comparación de ventas sí es completa."
    return _con_nota(datos, nota)


def _reputacion(ctx):
    """La reputación en Mercado Libre: nivel, MercadoLíder y las métricas que arman el nivel."""
    token = _token(ctx)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (ctx.cuenta_id,))
        fila = cursor.fetchone()
    if not fila:
        raise ErrorDeHerramienta("No encontré la cuenta de Mercado Libre.")
    rep = reputacion_mod.obtener_reputacion(token, fila[0])
    if not rep:
        raise ErrorDeHerramienta("Mercado Libre no devolvió la reputación ahora mismo. Probá de nuevo en un rato.")

    def _pct(metrica):
        return round(metrica["tasa"] * 100, 2) if metrica and metrica.get("tasa") is not None else None
    return {
        "nivel": rep["nivel_nombre"], "mercadolider": rep["power_seller_nombre"], "operaciones_que_mide_mercado_libre": rep["total_transacciones"], "completadas": rep["completadas"], "canceladas": rep["canceladas"],
        "metricas_que_arman_el_nivel_pct": {"reclamos": _pct(rep["reclamos"]), "demora_en_el_despacho": _pct(rep["demora_en_despacho"]), "cancelaciones": _pct(rep["cancelaciones_metrica"])},
        "aclaracion": "Mercado Libre arma el nivel con esas tres métricas; cuanto más bajas, mejor. Ya no informa calificaciones de vendedor: lo que opina la gente de cada modelo está en la pantalla Opiniones.",
        "origen": "pantalla Reputación (en Día a día)",
    }


def _monotributo(ctx):
    """Facturación de los últimos 12 meses contra el tope de la categoría de Monotributo, SOLO si la persona declaró que es monotributista."""
    condicion = fiscal.obtener(ctx.usuario_id, ctx.cuenta_id)
    if condicion != fiscal.MONOTRIBUTO:
        return {"aplica": False, "condicion_declarada": fiscal.etiqueta(condicion) if condicion else None,
                "mensaje": "Esta persona no declaró ser monotributista en CoreLux (se declara en la pantalla Monotributo): no se calcula nada. Para lo fiscal conviene consultar con un contador.", "origen": "pantalla Monotributo"}
    d = monotributo_mod.evaluar_categoria(ctx.usuario_id, ctx.cuenta_id)
    tope = d["tope_categoria_declarada"]
    return {
        "aplica": True, "facturacion_ultimos_12_meses": _plata(d["facturacion_12m"]), "categoria_que_corresponde_por_lo_facturado": d["categoria_real"], "categoria_declarada": d["categoria_declarada"],
        "tope_anual_de_la_categoria_declarada": _plata(tope) if tope else None, "porcentaje_del_tope_usado": round(d["facturacion_12m"] / tope * 100, 1) if tope else None,
        "te_queda_para_llegar_al_tope": _plata(tope - d["facturacion_12m"]) if tope else None,
        "cuota_mensual_de_la_categoria_declarada": _plata(d["cuota_mensual_declarada"]) if d["cuota_mensual_declarada"] else None,
        "variacion_de_lo_facturado_ultimos_3_meses_pct": d["variacion_pct_propia"], "meses_estimados_para_superar_el_tope": d["meses_para_cruzar"], "avisos": [a["texto"] for a in d["alertas"]],
        "escalas_vigentes_desde": d["vigente_desde"],
        "aclaracion": "Es una orientación con las escalas publicadas por ARCA, que se actualizan cada tanto: la categoría y los pasos a seguir hay que confirmarlos con un contador.",
        "origen": "pantalla Monotributo",
    }


def _sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def _palabras_de_busqueda(texto):
    palabras = [p for p in re.findall(r"[a-z0-9]+", _sin_acentos(str(texto or "")[:MAX_LARGO_DE_BUSQUEDA]).lower()) if len(p) >= 2][:MAX_PALABRAS_DE_BUSQUEDA]
    if not palabras:
        raise ErrorDeHerramienta("Decime qué producto buscás (al menos una palabra del título).")
    return palabras


def _producto(ctx, buscar=None):
    """Cómo viene un producto puntual: stock, precio y margen, ventas de 30 días, calidad, visitas y opiniones. Busca por palabras del título entre las publicaciones de ESTA cuenta."""
    palabras = _palabras_de_busqueda(buscar)
    desde, hasta = ctx.hoy - timedelta(days=DIAS_POR_DEFECTO - 1), ctx.hoy
    titulo_normalizado = "translate(lower(p.titulo), 'áéíóúüñ', 'aeiouun')"
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            f"""SELECT p.id, p.id_meli, p.titulo, p.estado, p.precio, COALESCE(p.precio_costo, 0), COALESCE(p.family_id, p.id_meli), p.calidad_score, p.visitas_14d, p.visitas_previas_14d,
                       p.opiniones_promedio, p.opiniones_total
                FROM productos_padre p WHERE p.cuenta_id = %s AND {" AND ".join([f"position(%s in {titulo_normalizado}) > 0"] * len(palabras))}
                ORDER BY (p.estado = 'active') DESC, p.titulo LIMIT 120""", (ctx.cuenta_id, *palabras))
        filas = cursor.fetchall()
        if not filas:
            return {"coincidencias": 0, "mensaje": "No encontré publicaciones de esta cuenta con esas palabras en el título. Probá con menos palabras o con otro nombre.", "origen": "pantallas Stock y Precios"}
        ids_meli, ids_padre = [f[1] for f in filas], [f[0] for f in filas]
        cursor.execute("""SELECT id_meli, COALESCE(SUM(cantidad), 0), COALESCE(SUM(precio_venta * cantidad), 0) FROM ventas
                          WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta BETWEEN %s AND %s AND id_meli = ANY(%s) GROUP BY id_meli""", (ctx.cuenta_id, desde, hasta, ids_meli))
        ventas = {r[0]: (int(r[1]), float(r[2])) for r in cursor.fetchall()}
        cursor.execute("""SELECT id_padre, COALESCE(SUM(COALESCE(stock_propio, 0) + COALESCE(stock_full, 0)), 0),
                                 COUNT(*) FILTER (WHERE COALESCE(stock_propio, 0) + COALESCE(stock_full, 0) = 0)
                          FROM productos_variantes WHERE cuenta_id = %s AND id_padre = ANY(%s) GROUP BY id_padre""", (ctx.cuenta_id, ids_padre))
        stock = {r[0]: (int(r[1]), int(r[2])) for r in cursor.fetchall()}
        precios = precios_mod.obtener_datos(cursor, ctx.cuenta_id, precios_mod.MARGEN_OBJETIVO_DEFECTO, 0.0)
    por_precio = {i["id_meli"]: i for i in precios["items"]}

    modelos = {}
    for id_padre, id_meli, titulo, estado, precio, costo, familia, calidad, visitas, previas, op_promedio, op_total in filas:
        m = modelos.setdefault(familia, {"titulos": [], "activas": 0, "pausadas": 0, "otras": 0, "precios": [], "sin_costo": 0, "unidades": 0, "facturado": 0.0, "stock": 0, "variantes_sin_stock": 0,
                                         "calidad": [], "visitas": 0, "previas": 0, "op": [], "estados_de_precio": {"pierden": 0, "justo": 0, "ok": 0}, "neto": 0.0, "venta_90": 0.0})
        m["titulos"].append(titulo or id_meli)
        m["activas" if estado == "active" else ("pausadas" if estado == "paused" else "otras")] += 1
        u, f = ventas.get(id_meli, (0, 0.0))
        m["unidades"] += u
        m["facturado"] += f
        if estado == "active":
            m["precios"].append(float(precio or 0))
            m["sin_costo"] += 1 if float(costo) <= 0 else 0
            s, sin = stock.get(id_padre, (0, 0))
            m["stock"] += s
            m["variantes_sin_stock"] += sin
            if id_meli in por_precio:
                p = por_precio[id_meli]
                m["estados_de_precio"][{"pierde": "pierden", "justo": "justo", "ok": "ok"}[p["estado"]]] += 1
                m["neto"] += p["neto_unitario"] * p["unidades"]
                m["venta_90"] += p["precio"] * p["unidades"]
        if calidad is not None:
            m["calidad"].append(int(calidad))
        m["visitas"] += int(visitas or 0)
        m["previas"] += int(previas or 0)
        if op_promedio is not None and (op_total or 0) > 0:
            m["op"].append((float(op_promedio), int(op_total)))

    resultado = []
    for m in sorted(modelos.values(), key=lambda m: (-m["unidades"], -m["activas"]))[:MAX_MODELOS_EN_PRODUCTO]:
        nombre, _ = costos_mod.nombres_de_variantes(list(dict.fromkeys(m["titulos"])))
        resultado.append({
            "producto": nombre or m["titulos"][0], "publicaciones_activas": m["activas"], "publicaciones_pausadas": m["pausadas"],
            "precio": {"minimo": _plata(min(m["precios"])), "maximo": _plata(max(m["precios"]))} if m["precios"] else None,
            "publicaciones_activas_sin_costo_de_fabricacion_cargado": m["sin_costo"],
            "stock": {"unidades": m["stock"], "variantes_activas_sin_stock": m["variantes_sin_stock"]},
            "ultimos_30_dias": {"unidades_vendidas": m["unidades"], "facturado": _plata(m["facturado"])},
            "margen_actual_pct": round(m["neto"] / m["venta_90"] * 100, 1) if m["venta_90"] > 0 else None,
            "estado_del_precio": {"pierden_plata": m["estados_de_precio"]["pierden"], "ganan_menos_que_tu_margen_objetivo": m["estados_de_precio"]["justo"], "cubren_tu_margen": m["estados_de_precio"]["ok"]},
            "calidad_promedio_de_mercado_libre": round(sum(m["calidad"]) / len(m["calidad"]), 1) if m["calidad"] else None,
            "visitas_14_dias": m["visitas"], "variacion_de_visitas_pct": round((m["visitas"] - m["previas"]) / m["previas"] * 100, 1) if m["previas"] > 0 else None,
            "opiniones": {"promedio": round(sum(p * t for p, t in m["op"]) / sum(t for _, t in m["op"]), 1), "cantidad": sum(t for _, t in m["op"])} if m["op"] else None,
        })
    return {"coincidencias": len(filas), "productos": resultado, "hay_mas_productos": max(0, len(modelos) - MAX_MODELOS_EN_PRODUCTO),
            "aclaracion": "El margen y el estado del precio usan la comisión y el envío reales de los últimos 90 días y el margen objetivo de 20%. Si hay más productos que coinciden, pedile a la persona que precise el nombre.",
            "origen": "pantallas Stock, Precios, Calidad y Opiniones"}


# ── Dónde, cuándo y cómo se entrega lo que se vende ─────────────────────────────────────────────────────────────────────────────────────

MIN_ORDENES_CUANDO_COMPRAN = 30        # con menos ventas el patrón por día y hora no dice nada (mismo criterio que la pantalla)
NOMBRES_DE_LOGISTICA = {"fulfillment": "FULL (lo despacha Mercado Libre)", "self_service": "Flex (entregás vos)", "sin_dato": "Todavía sin dato del envío"}


def _cuando_compran(filas):
    """
    Cuándo compran: de [(día ISO 1=lunes…7, hora, órdenes)] arma las órdenes por día de la semana, el mejor y el peor día y la mejor franja de 3 horas seguidas (puede cruzar la medianoche).
    Es el mismo cálculo de la pantalla Inicio. Con menos de MIN_ORDENES_CUANDO_COMPRAN órdenes no se saca ninguna conclusión.
    """
    total = sum(int(n) for _, _, n in filas)
    if total < MIN_ORDENES_CUANDO_COMPRAN:
        return {"ordenes": total, "aviso": f"Hay muy pocas ventas en el período ({total}): con menos de {MIN_ORDENES_CUANDO_COMPRAN} el día y la hora todavía no dicen nada. Probá con un período más largo."}
    por_dia = [{"dia": dashboard_mod.DIAS_SEMANA[i], "ordenes": 0} for i in range(7)]
    por_hora = [0] * 24
    for dia, hora, n in filas:
        por_dia[int(dia) - 1]["ordenes"] += int(n)
        por_hora[int(hora)] += int(n)
    for d in por_dia:
        d["pct_del_total"] = round(d["ordenes"] / total * 100)
    mejor = max(range(24), key=lambda h: sum(por_hora[(h + k) % 24] for k in range(3)))
    return {
        "ordenes": total, "por_dia_de_la_semana": por_dia, "mejor_dia": max(por_dia, key=lambda d: d["ordenes"])["dia"], "peor_dia": min(por_dia, key=lambda d: d["ordenes"])["dia"],
        "mejor_franja_de_3_horas": f"{mejor:02d} a {(mejor + 3) % 24:02d} h", "pct_de_las_ventas_en_esa_franja": round(sum(por_hora[(mejor + k) % 24] for k in range(3)) / total * 100),
        "aclaracion": "Hora de Argentina; sirve para elegir cuándo conviene lanzar una promoción, responder preguntas o activar publicidad.",
    }


def _resumen_de_logistica(filas):
    """De [(tipo de logística, órdenes, unidades, facturado, costo de envío)] arma el costo de envío de cada modalidad: por unidad y como % de lo facturado."""
    total_unidades = sum(int(f[2] or 0) for f in filas) or 1
    resultado = []
    for tipo, ordenes, unidades, facturado, envio in sorted(filas, key=lambda f: -float(f[3] or 0)):
        unidades, facturado, envio = int(unidades or 0), float(facturado or 0), float(envio or 0)
        resultado.append({
            "modalidad": NOMBRES_DE_LOGISTICA.get(tipo, "Correo / Mercado Envíos"), "ordenes": int(ordenes or 0), "unidades": unidades, "pct_de_las_unidades": round(unidades / total_unidades * 100),
            "facturado": _plata(facturado), "costo_de_envio": _plata(envio), "costo_de_envio_por_unidad": _plata(envio / unidades) if unidades else None,
            "costo_de_envio_pct_del_facturado": round(envio / facturado * 100, 1) if facturado > 0 else None,
        })
    return resultado


# ── Posventa, promociones, competencia, opiniones, conversión, precios, gastos, facturación y preguntas ───────────────────────────────────────

def _devoluciones(ctx, desde=None, hasta=None, dias=None):
    """Devoluciones, reclamos y cancelaciones del período: cuántos, cuáles afectan la reputación, por qué motivos y cuánta plata está retenida."""
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            f"""SELECT tipo, COUNT(*), COUNT(*) FILTER (WHERE {SQL_RECLAMO_AFECTA}), COUNT(*) FILTER (WHERE estado NOT IN ('closed', 'resolved')),
                       COALESCE(SUM(monto_retenido) FILTER (WHERE estado NOT IN ('closed', 'resolved')), 0)
                FROM incidencias_posventa WHERE cuenta_id = %s AND fecha BETWEEN %s AND %s GROUP BY tipo""", (ctx.cuenta_id, desde, hasta))
        por_tipo = {r[0]: r[1:] for r in cursor.fetchall()}
        cursor.execute("""SELECT tipo, motivo, COUNT(*) FROM incidencias_posventa WHERE cuenta_id = %s AND fecha BETWEEN %s AND %s AND motivo IS NOT NULL AND motivo <> ''
                          GROUP BY tipo, motivo ORDER BY 3 DESC LIMIT 12""", (ctx.cuenta_id, desde, hasta))
        motivos = cursor.fetchall()
        cursor.execute("SELECT COUNT(DISTINCT id_orden) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta BETWEEN %s AND %s", (ctx.cuenta_id, desde, hasta))
        ordenes = int(cursor.fetchone()[0] or 0)
        cursor.execute("""SELECT COUNT(DISTINCT id_orden), COALESCE(SUM(monto), 0) FROM ventas_retiradas
                          WHERE cuenta_id = %s AND motivo = 'cancelada' AND (fila->>'fecha_venta')::date BETWEEN %s AND %s""", (ctx.cuenta_id, desde, hasta))
        retiradas, monto_retirado = cursor.fetchone()

    def _tipo(clave):
        total, afectan, abiertos, retenido = por_tipo.get(clave, (0, 0, 0, 0))
        return {"cantidad": int(total), "afectan_la_reputacion": int(afectan), "todavia_abiertos": int(abiertos), "dinero_retenido": _plata(retenido)}
    total = sum(int(v[0]) for v in por_tipo.values())

    def _top(clave):
        return [{"motivo": m, "cantidad": int(n)} for t, m, n in motivos if t == clave][:5]
    datos = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "ventas_del_periodo": ordenes,
        "devoluciones": _tipo("return"), "reclamos": _tipo("claim"), "cancelaciones": _tipo("cancelacion"),
        "motivos_de_devolucion": _top("return"), "motivos_de_reclamo": _top("claim"),
        "ventas_canceladas_o_reembolsadas_que_ya_no_cuentan": {"ordenes": int(retiradas or 0), "monto": _plata(monto_retirado)},
        "aprox_casos_cada_100_ventas": round(total / ordenes * 100, 1) if ordenes else None,
        "aclaracion": "Solo los reclamos que Mercado Libre marca como «afecta la reputación» pesan en tu nivel; los demás igual se gestionan y pueden retener plata. Lo de «cada 100 ventas» es aproximado: los casos del período pueden venir de ventas anteriores.",
        "origen": "pantallas Ganancia Real y Reputación",
    }
    return _con_nota(datos, nota)


def _promociones(ctx):
    """Promociones y descuentos: qué pasó con las ventas en las últimas, cupones que financia la persona, stock que rota lento (candidato a promoción) y campañas de Mercado Libre."""
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        impacto = promociones_mod.obtener_impacto_promociones(cursor)
        cupones = promociones_mod.obtener_cupones(cursor, ctx.cuenta_id, 30)
        candidatos = promociones_mod.sugerir_candidatos_promocion(cursor)
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (ctx.cuenta_id,))
        fila = cursor.fetchone()
    campanas, campanas_ok = [], False
    try:
        if fila:
            campanas = promociones_mod.formatear_campanias_para_vista(promociones_mod.obtener_promociones_usuario(_token(ctx), fila[0]))
            campanas_ok = True
    except ErrorDeHerramienta:
        pass
    return {
        "ultimas_promociones": [{"publicacion": i["titulo"], "precio_antes": _plata(i["precio_original"]), "precio_en_promocion": _plata(i["precio_promo"]), "desde": i["fecha_inicio"], "hasta": i["fecha_fin"],
                                 "sigue_activa": i["activo"], "ventas_por_dia_antes": i["promedio_previo"], "ventas_por_dia_durante": i["promedio_durante"], "variacion_de_las_ventas_pct": i["variacion_pct"]}
                                for i in impacto[:8]],
        "cupones_que_pagaste_ultimos_30_dias": {"total": cupones["total"], "ventas_con_cupon": cupones["ventas_con_cupon"], "pct_de_lo_facturado": cupones["pct_facturado"],
                                                "los_que_mas_costaron": [{"publicacion": t["titulo"], "total": t["total"]} for t in cupones["top"][:5]]} if cupones else None,
        "stock_que_rota_lento_candidato_a_promocion": [{"publicacion": c["titulo"], "unidades_en_stock": c["stock_total"], "ventas_ultimos_14_dias": c["unidades_14d"], "plata_inmovilizada_a_precio_de_lista": c["capital_inmovilizado"]}
                                                       for c in candidatos[:6]],
        "campanas_de_mercado_libre": [{"campana": c["nombre"], "tipo": c["tipo_texto"], "estado": c["estado_texto"], "desde": c["vigencia_desde"], "hasta": c["vigencia_hasta"]} for c in campanas[:8]] if campanas_ok else None,
        "aclaracion": "Si la lista de campañas de Mercado Libre viene vacía puede que no haya ninguna o que Mercado Libre no haya respondido. Las promociones se gestionan en la pantalla Promociones.",
        "origen": "pantalla Promociones",
    }


def _competencia(ctx):
    """Las dos fuentes de la pantalla Competencia: las publicaciones de catálogo de la cuenta (si ganan el puesto principal y a qué precio se ganaría, cruzado con el precio mínimo) y los productos
    de catálogo que la persona sigue (precio más bajo, cantidad de ofertas y vendedores, cómo se movió). Las dos solo se leen."""
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        d = catalogo_mod.obtener(cursor, ctx.cuenta_id)
        seguidos = espia_competencia.obtener_panorama_competencia(cursor, ctx.cuenta_id)
    resultado = {"origen": "pantalla Competencia", "tiene_publicaciones_de_catalogo": bool(d)}
    resultado["productos_que_sigue"] = [_producto_seguido(p) for p in seguidos[:6]]
    if not d:
        resultado["mensaje"] = ("Esta cuenta no tiene publicaciones de catálogo con datos de competencia todavía, así que no hay un precio para ganar que comparar."
                                + ("" if seguidos else " Tampoco sigue ningún producto de catálogo: pegando el link de una ficha en la pantalla Competencia se empieza a ver cuántos vendedores la ofrecen y a qué precio."))
        return resultado
    accionables = [i for i in d["items"] if i["estado"] == "competing"]
    resultado.update({
        "ganando_el_puesto_principal": d["ganando"], "compitiendo": d["perdiendo"], "conviene_bajar_el_precio": d["conviene_bajar"],
        "las_que_compiten": [{"publicacion": i["titulo"], "tu_precio": _plata(i["precio"]), "precio_para_ganar": i["para_ganar"], "diferencia_pct": i["diferencia_pct"],
                              "ganancia_por_unidad_a_ese_precio": i["neto_para_ganar"], "conviene": i["conviene"], "estado": i["texto"], "condiciones": [c["descripcion"] for c in i["condiciones"] if c.get("descripcion")][:3]}
                             for i in accionables[:8]],
        "aclaracion": "«Conviene» significa que a ese precio todavía queda ganancia, con la comisión, el envío y el costo reales. Mercado Libre informa los precios y la cantidad de ofertas, no cuánto vende cada competidor.",
    })
    return resultado


def _producto_seguido(p):
    """Un producto de catálogo que la persona sigue, resumido con lo último que se midió y cómo cambió el precio más bajo en el historial guardado."""
    historial = p["historial"]
    hoy = historial[0] if historial else {}
    primero = historial[-1] if len(historial) > 1 else {}
    variacion = None
    if hoy.get("precio_min") and primero.get("precio_min"):
        variacion = round((hoy["precio_min"] - primero["precio_min"]) / primero["precio_min"] * 100, 1)
    return {"producto": str(p["alias"] or p["titulo_actual"] or p["id_producto"])[:80], "precio_mas_bajo": hoy.get("precio_min"), "precio_mediano": hoy.get("precio_mediano"), "ofertas": hoy.get("ofertas"), "vendedores": hoy.get("vendedores"),
            "ofertas_con_full_pct": hoy.get("pct_full"), "como_se_movio_el_precio_mas_bajo": p["tendencia_precio"], "variacion_del_precio_mas_bajo_pct": variacion, "dias_con_datos": len(historial), "ultima_medicion": hoy.get("fecha")}


def _opiniones(ctx):
    """Lo que dicen las opiniones de los modelos: calificación, porcentaje de críticas y lo que MeLi resume de cada uno (talle, calidad…). Solo cifras y resúmenes de Mercado Libre, nunca los comentarios."""
    with _conexion(ctx) as conexion:
        d = opiniones_mod.obtener_datos(conexion.cursor(), ctx.cuenta_id)
    if not d["total_opiniones"]:
        return {"hay_opiniones": False, "mensaje": "Todavía no hay opiniones guardadas de los productos de esta cuenta.", "origen": "pantalla Opiniones"}

    def _modelo(f):
        return {"modelo": f["titulo"], "calificacion": f["promedio"], "opiniones": f["total"], "pct_de_criticas_1_y_2_estrellas": f["pct_criticas"], "unidades_vendidas_recientes": f["unidades"],
                "resumen_de_mercado_libre": [a["texto"] for a in f["atributos"] if a.get("texto")][:3]}
    return {
        "hay_opiniones": True, "calificacion_promedio": d["promedio"], "opiniones_en_total": d["total_opiniones"], "pct_buenas_4_y_5_estrellas": d["pct_buenas"], "pct_malas_1_y_2_estrellas": d["pct_malas"],
        "modelos_sin_opiniones": d["sin_opiniones"], "modelos_para_revisar": [_modelo(f) for f in d["revisar"][:5]],
        "los_mas_opinados": [_modelo(f) for f in d["productos"][:5]],
        "aclaracion": "Un modelo se marca «para revisar» con calificación baja o muchas críticas y opiniones suficientes. Los comentarios de la gente se leen en la pantalla Opiniones.", "origen": "pantalla Opiniones",
    }


def _conversion(ctx):
    """De las visitas a las ventas por modelo (últimos 14 días): cuáles tienen mucho tráfico y venden poco (revisar la publicación) y cuáles venden bien lo poco que se ve (falta tráfico)."""
    desde = ctx.hoy - timedelta(days=13)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""SELECT p.id_meli, p.titulo, COALESCE(p.family_id, p.id_meli), COALESCE(p.visitas_14d, 0), COALESCE(p.visitas_previas_14d, 0) FROM productos_padre p
                          WHERE p.cuenta_id = %s AND p.estado = 'active' AND p.visitas_en IS NOT NULL""", (ctx.cuenta_id,))
        filas = cursor.fetchall()
        cursor.execute("SELECT id_meli, COALESCE(SUM(cantidad), 0) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta BETWEEN %s AND %s GROUP BY id_meli", (ctx.cuenta_id, desde, ctx.hoy))
        vendidas = {r[0]: int(r[1]) for r in cursor.fetchall()}
    if not filas:
        return {"hay_datos": False, "mensaje": "Todavía no hay visitas guardadas de las publicaciones activas (se completan de a poco en cada sincronización).", "origen": "pantalla Embudo de Conversión"}
    modelos = {}
    for id_meli, titulo, familia, visitas, previas in filas:
        m = modelos.setdefault(familia, {"titulos": [], "visitas": 0, "previas": 0, "unidades": 0})
        m["titulos"].append(titulo or id_meli)
        m["visitas"] += int(visitas)
        m["previas"] += int(previas)
        m["unidades"] += vendidas.get(id_meli, 0)
    visitas_totales = sum(m["visitas"] for m in modelos.values())
    conversion_global = sum(m["unidades"] for m in modelos.values()) / visitas_totales * 100 if visitas_totales else 0.0
    filas_modelo = []
    for m in modelos.values():
        nombre, _ = costos_mod.nombres_de_variantes(list(dict.fromkeys(m["titulos"])))
        filas_modelo.append({"modelo": nombre or m["titulos"][0], "visitas_14_dias": m["visitas"], "ventas_14_dias": m["unidades"], "conversion_pct": round(m["unidades"] / m["visitas"] * 100, 2) if m["visitas"] else None,
                             "variacion_de_visitas_pct": round((m["visitas"] - m["previas"]) / m["previas"] * 100, 1) if m["previas"] > 0 else None,
                             "diagnostico": embudo_mod.diagnosticar(m["visitas"], m["unidades"], conversion_global)})
    revisar = sorted((f for f in filas_modelo if f["diagnostico"] == "revisar_ficha"), key=lambda f: -f["visitas_14_dias"])
    falta_trafico = sorted((f for f in filas_modelo if f["diagnostico"] == "poca_visibilidad"), key=lambda f: -f["ventas_14_dias"])
    return {
        "hay_datos": True, "visitas_14_dias": visitas_totales, "conversion_promedio_de_la_cuenta_pct": round(conversion_global, 2),
        "mucho_trafico_y_poca_venta_revisar_la_publicacion": [{k: v for k, v in f.items() if k != "diagnostico"} for f in revisar[:6]],
        "venden_bien_pero_se_ven_poco_falta_trafico": [{k: v for k, v in f.items() if k != "diagnostico"} for f in falta_trafico[:6]],
        "aclaracion": f"Solo se juzga con al menos {embudo_mod.MIN_VISITAS_PARA_JUZGAR} visitas y contra el promedio de la propia cuenta (cada rubro y precio convierte distinto). La conversión es ventas divididas por visitas de los últimos 14 días.",
        "origen": "pantalla Embudo de Conversión (visitas guardadas por Mercado Libre)",
    }


def _historial_de_precios(ctx):
    """Los últimos cambios de precio y qué pasó con las ventas de esa publicación en los 7 días de antes y de después."""
    with _conexion(ctx) as conexion:
        cambios = historial_mod.obtener_historial_con_impacto(conexion.cursor(), 7, 30)
    return {
        "cambios_recientes": [{"publicacion": c["titulo"], "fecha": c["fecha_cambio"], "precio_anterior": _plata(c["precio_anterior"]), "precio_nuevo": _plata(c["precio_nuevo"]), "movimiento": "subió" if c["precio_nuevo"] > c["precio_anterior"] else "bajó",
                               "unidades_7_dias_antes": c["unidades_antes"], "unidades_7_dias_despues": c["unidades_despues"], "variacion_de_las_ventas_pct": c["variacion_pct"], "datos_incompletos": c["datos_incompletos"]}
                              for c in cambios[:10]],
        "aclaracion": "Es una comparación simple de unidades vendidas antes y después: no prueba que el precio sea la causa (también influyen la temporada, la publicidad y el stock). Sin ventas antes del cambio no hay comparación.",
        "origen": "pantalla Historial de Precios",
    }


def _gastos(ctx, desde=None, hasta=None, dias=None):
    """Gastos operativos cargados (alquiler, embalaje, sueldos…): fijos y variables del período, con los recurrentes prorrateados por día."""
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""SELECT concepto, categoria, monto, fecha, recurrente, fecha_fin FROM gastos_operativos
                          WHERE cuenta_id = %s AND eliminado_en IS NULL AND ((recurrente = false AND fecha BETWEEN %s AND %s) OR (recurrente = true AND fecha <= %s AND (fecha_fin IS NULL OR fecha_fin >= %s)))""",
                       (ctx.cuenta_id, desde, hasta, hasta, desde))
        filas = cursor.fetchall()
    fijos = variables = 0.0
    lista = []
    for concepto, categoria, monto, fecha, recurrente, fecha_fin in filas:
        monto_del_periodo = prorratear_mensual(float(monto), fecha, fecha_fin, desde, hasta) if recurrente else float(monto)
        if categoria == "fijo":
            fijos += monto_del_periodo
        else:
            variables += monto_del_periodo
        lista.append({"concepto": concepto, "tipo": "fijo" if categoria == "fijo" else "variable", "monto_en_el_periodo": _plata(monto_del_periodo), "recurrente": bool(recurrente)})
    lista.sort(key=lambda g: -g["monto_en_el_periodo"])
    return _con_nota({
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "gastos_fijos": _plata(fijos), "gastos_variables": _plata(variables), "total": _plata(fijos + variables), "cantidad_de_gastos": len(lista), "los_mas_grandes": lista[:8],
        "aclaracion": "Son los gastos que la persona cargó en la pantalla Costos (alquiler, embalaje, sueldos…). No están restados de la «ganancia neta real» de Ganancia Real, que cuenta lo que deja cada venta; sirven para el punto de equilibrio y el reporte fiscal.",
        "origen": "pantalla Costos",
    }, nota)


def _cargos_de_mercado_libre(ctx):
    """La factura de Mercado Libre del período en curso agrupada por rubro (comisiones, envíos, publicidad, impuestos, bonificaciones)."""
    resumen = facturacion_mod.resumen_condensado_periodo_actual(_token(ctx), ctx.cuenta_id)
    if not resumen:
        raise ErrorDeHerramienta("Mercado Libre no devolvió la factura del período ahora mismo. Probá de nuevo en un rato.")
    return {
        "periodo": {"desde": resumen["date_from"], "hasta": resumen["date_to"], "en_curso": resumen["en_curso"]}, "total_facturado_por_mercado_libre": _plata(sum(f["monto"] for f in resumen["filas"])),
        "por_rubro": [{"rubro": f["label"], "monto": _plata(f["monto"])} for f in resumen["filas"]],
        "aclaracion": "Los montos en negativo son bonificaciones a favor. Los períodos de facturación de Mercado Libre van del 9 al 8. Los envíos Flex los cobra tu propia logística y no figuran en esta factura.",
        "origen": "pantalla Facturación",
    }


def _preguntas(ctx):
    """Preguntas de la gente: cuántas esperan respuesta, cuánto hace que espera la más vieja, cuántas pasaron el objetivo de CoreLux y cuánto tarda la persona en responder (sin leer el texto)."""
    with _conexion(ctx) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""SELECT COUNT(*), MIN(fecha_pregunta), COUNT(*) FILTER (WHERE hora_limite_respuesta IS NOT NULL AND hora_limite_respuesta < now())
                          FROM preguntas_pendientes WHERE cuenta_id = %s AND estado = 'pendiente'""", (ctx.cuenta_id,))
        pendientes, mas_vieja, vencidas = cursor.fetchone()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (ctx.cuenta_id,))
        fila = cursor.fetchone()
    horas = None
    if mas_vieja is not None:
        referencia = datetime.now(mas_vieja.tzinfo) if mas_vieja.tzinfo else datetime.now(timezone.utc).replace(tzinfo=None)
        horas = max(0, round((referencia - mas_vieja).total_seconds() / 3600))
    tiempo = None
    try:
        tiempo = tiempo_respuesta_mod.calcular(_token(ctx), fila[0]) if fila else None
    except ErrorDeHerramienta:
        pass
    return {
        "preguntas_sin_responder": int(pendientes), "horas_de_la_mas_vieja": horas, "pasaron_el_objetivo_de_una_hora": int(vencidas),
        "tiempo_de_respuesta": {"mediana_en_minutos": tiempo["mediana_min"], "pct_respondidas_en_menos_de_1_hora": tiempo["pct_en_1h"], "preguntas_medidas": tiempo["muestra"]} if tiempo else None,
        "aclaracion": "El objetivo de una hora es de CoreLux (no un plazo de Mercado Libre). Responder rápido ayuda a vender y a la reputación. Si el tiempo de respuesta viene vacío, Mercado Libre no respondió o no hay preguntas respondidas. Las preguntas se responden en la pantalla Preguntas.",
        "origen": "pantalla Día a día (Preguntas)",
    }


def _texto_de_cortes(cortes):
    """Los horarios de corte en palabras; sin dato se dice que falta (nunca un horario supuesto)."""
    correo = cortes["correo"]
    texto_correo = {"informado": f"hoy a las {correo['hora']}", "sin_retiro": "hoy el correo no retira"}.get(correo["estado"], "Mercado Libre no informó el horario de corte del correo")
    return {"correo": texto_correo, "flex": f"hoy a las {cortes['flex']}" if cortes["flex"] else "la persona todavía no lo cargó (se carga en Mi cuenta)"}


def _despacho(ctx):
    """
    Lo que hay para despachar HOY, de lo guardado en la base (sin llamar a Mercado Libre ni escribir nada): cuántos paquetes faltan, de qué modalidad y de qué productos. Usa la misma consulta
    que la pantalla (despacho.leer_paquetes_guardados) y el mismo día de despacho (el que arma el horario de corte). FULL no figura: lo despacha Mercado Libre.
    """
    with _conexion(ctx) as conexion:
        cortes = despacho_corte.cortes_guardados(conexion.cursor(), ctx.cuenta_id, ctx.hoy)
        hora = cortes["hora_agrupacion"]
        filas = despacho_mod.leer_paquetes_guardados(conexion, ctx.hoy, 24 - hora)
    pendientes = [f for f in filas if not f["despachado"]]
    por_modalidad, por_variante = {}, {}
    for f in pendientes:
        modalidad = despacho_mod._tipo_envio_legible(f["tipo_logistica"])
        grupo = por_modalidad.setdefault(modalidad, {"modalidad": modalidad, "paquetes": 0, "unidades": 0})
        grupo["paquetes"] += 1
        grupo["unidades"] += int(f["cantidad"] or 0)
        clave = (limpiar_titulo_modelo(f["titulo"], f["talle_real"]), rotulo_variante(f["etiqueta_variante"], f["talle_real"]))
        por_variante[clave] = por_variante.get(clave, 0) + int(f["cantidad"] or 0)
    ranking = sorted(por_variante.items(), key=lambda x: (-x[1], x[0]))
    return {
        "dia_de_despacho": ctx.hoy.isoformat(),
        "paquetes_del_dia": len(filas), "ya_despachados": len(filas) - len(pendientes), "pendientes_de_despachar": len(pendientes),
        "unidades_pendientes": sum(g["unidades"] for g in por_modalidad.values()),
        "pendientes_por_modalidad": sorted(por_modalidad.values(), key=lambda g: (-g["paquetes"], g["modalidad"])),
        "que_hay_que_preparar": [{"modelo": modelo, "variante": variante, "unidades": unidades} for (modelo, variante), unidades in ranking[:8]],
        "otros_modelos_o_variantes_pendientes": max(0, len(ranking) - 8),
        "horarios_de_corte": _texto_de_cortes(cortes),
        "que_dias_abarca": f"las ventas desde ayer a las {hora:02d}:00 hasta hoy a las {hora:02d}:00 (las de después del corte entran al despacho de mañana)" if hora < 24 else "las ventas de hoy, día calendario (no hay un horario de corte conocido)",
        "aclaracion": ("Es lo último que quedó guardado: un paquete figura como despachado cuando Mercado Libre lo avisa o cuando se abre la pantalla Despacho, que lo verifica contra Mercado Libre. Lo que todavía no tiene "
                       "el tipo de envío confirmado se cuenta como Correo, igual que en la pantalla. El horario límite de cada paquete se ve solo ahí."),
        "origen": "pantalla Día a día (Despacho)",
    }


def _panorama(ctx):
    """El panorama general en una sola llamada: hoy, últimos 30 días, mes en curso, modelos más vendidos y stock en riesgo (el resumen de siempre del asistente)."""
    datos = chat_ia._armar_contexto(ctx.usuario_id, ctx.cuenta_id)
    datos.pop("ventas_por_dia_ultimos_30_dias", None)
    datos["origen"] = "pantallas Inicio, Ganancia Real y Stock"
    return datos


# ── Registro ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

_PERIODO = {"dias": {"type": "integer", "description": "Los últimos N días contando hoy (1 = solo hoy, 7, 30, 90). USALO para «hoy», «esta semana», «los últimos 30 días»: no calcules fechas. Si se manda, se ignoran desde y hasta."},
            "desde": {"type": "string", "description": "Fecha inicial AAAA-MM-DD, solo para un período con fechas concretas (por ejemplo «septiembre»). Por defecto, hace 30 días."},
            "hasta": {"type": "string", "description": "Fecha final AAAA-MM-DD (por defecto, hoy)."}}

HERRAMIENTAS = {
    "ventas": {
        "descripcion": ("Ventas netas (sin canceladas ni devueltas) de un período: facturado, unidades y órdenes. `agrupar`: total, dia (por día), modelo (ranking de modelos con todas sus variantes juntas: usalo para «el producto o modelo más vendido»), "
                        "variante (ranking por variante: solo si preguntan por un tamaño, color u otra variante puntual), provincia (dónde se vende más), horario (qué día y a qué hora compran más: sirve para elegir cuándo promocionar) "
                        "o logistica (cuánto cuesta el envío de cada modalidad: FULL, Flex o Correo, por unidad y como % de lo facturado)."),
        "parametros": {**_PERIODO, "agrupar": {"type": "string", "enum": ["total", "dia", "modelo", "variante", "provincia", "horario", "logistica"]}}, "funcion": _ventas},
    "ganancia_real": {
        "descripcion": "Ganancia neta real de un período con todo el desglose (cargos de Mercado Libre, envíos, publicidad, costo de fabricación, cargos mensuales) y el margen. Es lo que queda de verdad.",
        "parametros": dict(_PERIODO), "funcion": _ganancia_real},
    "stock": {"descripcion": "Estado del stock: unidades propias y en FULL, variantes sin stock, las que se agotan pronto y las variantes clave que se quedaron sin stock.", "parametros": {}, "funcion": _stock},
    "posventa": {"descripcion": "Reclamos abiertos que afectan la reputación, devoluciones, dinero retenido y preguntas sin responder (cuántas y hace cuánto la más vieja).", "parametros": {}, "funcion": _posventa},
    "calidad": {"descripcion": "Calidad de las publicaciones según Mercado Libre: puntaje promedio, mejoras pendientes más repetidas, visitas y conversión.", "parametros": {}, "funcion": _calidad},
    "mercado": {"descripcion": "Qué se busca en Mercado Libre en las categorías donde vende la persona (puesto de cada búsqueda) y cómo está la oferta de su categoría principal.", "parametros": {}, "funcion": _mercado},
    "cobros": {"descripcion": "Cuándo y cuánta plata se acredita (hoy, mañana, 7 días), lo acreditado hace poco y el dinero retenido por reclamos.", "parametros": {}, "funcion": _cobros},
    "pendientes": {"descripcion": "Qué tiene que atender la persona hoy (misiones por prioridad) y la salud de su cuenta con el motivo de cada descuento.", "parametros": {}, "funcion": _pendientes},
    "costos": {"descripcion": "Cuántas publicaciones activas no tienen costo de fabricación cargado, qué parte de lo vendido queda sin costo (infla la ganancia) y el dólar que usa para los costos en USD.",
               "parametros": {}, "funcion": _costos},
    "ganancia_por_modelo": {
        "descripcion": "Qué modelos dejan más ganancia y cuáles pierden plata en un período (ganancia neta, ganancia por unidad y margen de cada modelo, con todas sus variantes juntas). Usala para «qué producto me conviene», «qué me deja más margen» o «qué vendo a pérdida».",
        "parametros": dict(_PERIODO), "funcion": _ganancia_por_modelo},
    "publicidad": {
        "descripcion": "Product Ads de Mercado Libre en un período: cuánto se gastó, cuánto vendió la publicidad, el retorno (ROAS) contra el punto de equilibrio, cada campaña y las publicaciones que gastan sin vender.",
        "parametros": dict(_PERIODO), "funcion": _publicidad},
    "precios": {
        "descripcion": "Precio mínimo (ganancia cero) y recomendado de las publicaciones: cuáles pierden plata al precio actual y cuáles ganan menos que el margen objetivo.",
        "parametros": {"margen_objetivo": {"type": "number", "description": "Margen objetivo en % del precio, de 0 a 60. Por defecto 20."}}, "funcion": _precios},
    "comparar_periodos": {
        "descripcion": "Compara un período contra el anterior de igual largo: facturado, unidades, órdenes, ganancia neta real, margen y cada costo (cargos, envíos, publicidad, fabricación). Usala para «¿mejoré o empeoré?», «¿cómo vengo contra el mes pasado?».",
        "parametros": {"dias": {"type": "integer", "description": "Largo del período en días contando hoy (por defecto 30). Se compara contra los mismos días inmediatamente anteriores."},
                       "modo": {"type": "string", "enum": ["dias", "mes"], "description": "dias (por defecto) o mes: lo que va del mes en curso contra el mismo tramo del mes anterior."}}, "funcion": _comparar_periodos},
    "reputacion": {"descripcion": "La reputación en Mercado Libre: nivel, MercadoLíder y las tasas de reclamos, demora en el despacho y cancelaciones que arman el nivel.", "parametros": {}, "funcion": _reputacion},
    "monotributo": {"descripcion": "Lo facturado en 12 meses contra el tope de la categoría de Monotributo y si conviene recategorizarse (solo si la persona declaró que es monotributista). Es orientativo: siempre confirmarlo con un contador.",
                    "parametros": {}, "funcion": _monotributo},
    "producto": {
        "descripcion": "Cómo viene UN producto puntual: stock, precios, margen, ventas de los últimos 30 días, calidad, visitas y opiniones. Buscalo por palabras de su título (por ejemplo «campera jean» o «iphone 14»).",
        "parametros": {"buscar": {"type": "string", "description": "Palabras del título del producto, sin la marca de la tienda ni signos."}}, "funcion": _producto},
    "panorama": {"descripcion": "El panorama general del negocio en una sola llamada: ventas de hoy, últimos 30 días, mes en curso con su proyección, modelos más vendidos y stock en riesgo. Usala para preguntas abiertas como «¿cómo voy?» o «dame un resumen».",
                 "parametros": {}, "funcion": _panorama},
    "devoluciones": {"descripcion": "Devoluciones, reclamos y cancelaciones de un período: cuántos, cuáles afectan la reputación, los motivos más repetidos, la plata retenida y las ventas canceladas o reembolsadas. Usala para «¿por qué me devuelven?» o «¿tengo muchos reclamos?».",
                     "parametros": dict(_PERIODO), "funcion": _devoluciones},
    "promociones": {"descripcion": "Promociones y descuentos: qué pasó con las ventas en las últimas promociones, cupones que paga la persona, stock que rota lento (candidato a promoción) y campañas de Mercado Libre disponibles.",
                    "parametros": {}, "funcion": _promociones},
    "tendencias": {"descripcion": ("Las búsquedas en tendencia de Mercado Libre en las categorías donde vende la persona, cuáles de ellas YA están en un título suyo y cuáles no (oportunidades), las fechas comerciales que se vienen y cómo se mueve la oferta de las categorías que sigue. "
                                   "Usala junto con «mercado» y «competencia» para preguntas de qué se busca, qué viene o qué conviene publicar."),
                   "parametros": {}, "funcion": _tendencias},
    "competencia": {"descripcion": ("Competencia en catálogo: las publicaciones de la cuenta que ganan o no el puesto principal (a qué precio se ganaría y si a ese precio todavía queda ganancia) y los productos de catálogo que la persona sigue "
                                    "(precio más bajo, cantidad de ofertas y vendedores, y cómo se movió). Si la cuenta no tiene publicaciones de catálogo igual devuelve lo que sigue."),
                    "parametros": {}, "funcion": _competencia},
    "opiniones": {"descripcion": "Lo que dicen las opiniones de los productos: calificación promedio, porcentaje de críticas, los modelos para revisar y el resumen que arma Mercado Libre de cada uno. No incluye los comentarios.",
                  "parametros": {}, "funcion": _opiniones},
    "conversion": {"descripcion": "De las visitas a las ventas por modelo (14 días): cuáles tienen mucho tráfico y venden poco (revisar la publicación) y cuáles venden bien pero se ven poco (falta tráfico).",
                   "parametros": {}, "funcion": _conversion},
    "historial_de_precios": {"descripcion": "Los últimos cambios de precio y qué pasó con las ventas de esa publicación en los 7 días de antes y de después.", "parametros": {}, "funcion": _historial_de_precios},
    "gastos": {"descripcion": "Gastos operativos cargados por la persona (alquiler, embalaje, sueldos…): fijos y variables de un período, con los más grandes.", "parametros": dict(_PERIODO), "funcion": _gastos},
    "cargos_de_mercado_libre": {"descripcion": "La factura de Mercado Libre del período en curso agrupada por rubro: comisiones, envíos, publicidad, impuestos y bonificaciones. Usala para «¿en qué me cobra Mercado Libre?».",
                                "parametros": {}, "funcion": _cargos_de_mercado_libre},
    "preguntas": {"descripcion": "Las preguntas de la gente: cuántas esperan respuesta, hace cuánto espera la más vieja, cuántas pasaron el objetivo de una hora y cuánto tarda la persona en responder. No lee el texto de las preguntas.",
                  "parametros": {}, "funcion": _preguntas},
    "despacho": {"descripcion": ("Lo que hay para despachar hoy (Correo y Flex; FULL lo despacha Mercado Libre): cuántos paquetes faltan, de qué modalidad, qué productos y variantes hay que preparar y los horarios de corte. "
                                 "Usala para «¿qué tengo para despachar?» o «¿cuánto me falta enviar hoy?». Es de hoy y de lo último guardado."),
                 "parametros": {}, "funcion": _despacho},
}


def definiciones():
    """Las herramientas en el formato de llamadas a funciones del proveedor."""
    return [{"type": "function", "function": {"name": nombre, "description": h["descripcion"], "parameters": {"type": "object", "properties": h["parametros"]}}} for nombre, h in HERRAMIENTAS.items()]


def ejecutar(nombre, argumentos, ctx):
    """Corre una herramienta y devuelve SIEMPRE un diccionario {"ok": True, "datos": …} o {"ok": False, "error": "texto"}; jamás levanta una excepción (un fallo no puede tumbar la conversación)."""
    herramienta = HERRAMIENTAS.get(nombre)
    if not herramienta:
        return {"ok": False, "error": f"No existe la herramienta «{nombre}». Las disponibles son: {', '.join(HERRAMIENTAS)}."}
    try:
        args = json.loads(argumentos) if isinstance(argumentos, str) and argumentos.strip() else (argumentos or {})
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        return {"ok": False, "error": "Los argumentos tienen que ser un objeto JSON."}
    try:
        datos = herramienta["funcion"](ctx, **{k: v for k, v in args.items() if k in herramienta["parametros"]})
    except ErrorDeHerramienta as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        print(f"[Asistente] ⚠️ La herramienta {nombre} falló: {type(e).__name__}: {e}")
        return {"ok": False, "error": "No pude leer ese dato ahora mismo."}
    return {"ok": True, "datos": datos}


# ── A dónde se puede llevar a la persona ──────────────────────────────────────────────────────────────────────────────────────────────────

def destinos():
    """{clave: {"texto", "url"}} de TODAS las pantallas del menú (nav_config) más Mi cuenta. Es la única lista de la que sale un botón de «ir a»: el modelo escribe la clave y el servidor pone el link."""
    lista = {}
    for seccion in nav_config.GRUPOS_NAV.values():
        for pagina in seccion["paginas"]:
            lista[pagina["nav_key"]] = {"texto": pagina["label"], "url": pagina["href"] + (f"#{pagina['ancla']}" if pagina.get("ancla") else "")}
    lista["cuenta"] = {"texto": "Mi cuenta", "url": "/cuenta"}
    lista["dolar"] = {"texto": "Dólar para tus costos", "url": "/cuenta#dolar"}
    return lista

"""
Herramientas de SOLO LECTURA del asistente de IA (asistente.py).

La IA nunca toca la base ni escribe SQL: cuando necesita un dato pide una de estas funciones por su nombre y recibe un resultado ACOTADO (períodos de hasta 92 días, rankings de 10, sin nombres,
direcciones ni mensajes de compradores). Cada una abre `db.conexion_usuario(usuario_id, cuenta_id)` —o sea, con RLS— y además filtra por `cuenta_id` en la consulta: aunque una política
fallara, una cuenta no podría leer los datos de otra. Ninguna escribe nada. Todo lo que devuelven es DATO, no instrucciones (el prompt del asistente se lo dice al modelo).
"""
import json
from datetime import date, datetime, timedelta, timezone

import analisis_stock
import calidad as calidad_mod
import cobros as cobros_mod
import costos as costos_mod
import dashboard as dashboard_mod
import db
import dolar as dolar_mod
import logros as logros_mod
import mercado as mercado_mod
import metricas
import nav_config
import salud_cuenta
from auth import token_manager
from utils import SQL_RECLAMO_AFECTA, hoy_argentina, limpiar_titulo_modelo, rotulo_variante, sql_variante_de_venta

MAX_DIAS = 92
DIAS_POR_DEFECTO = 30


class ErrorDeHerramienta(Exception):
    """Un pedido que no se puede atender; el texto se le devuelve al modelo (sin códigos ni datos técnicos) para que lo explique."""


class Contexto:
    def __init__(self, usuario_id, cuenta_id, hoy=None):
        self.usuario_id, self.cuenta_id, self.hoy = usuario_id, cuenta_id, hoy or hoy_argentina()


def _conexion(ctx):
    return db.conexion_usuario(ctx.usuario_id, ctx.cuenta_id)


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
    agrupar = agrupar if agrupar in ("total", "dia", "modelo", "variante") else "total"
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
    return _con_nota(datos, nota)


def _ganancia_real(ctx, desde=None, hasta=None, dias=None):
    desde, hasta, nota = _periodo(ctx, desde, hasta, dias)
    try:
        access_token = token_manager.asegurar_token_valido(ctx.cuenta_id)
    except token_manager.CuentaDesconectada:
        raise ErrorDeHerramienta("La cuenta de Mercado Libre está desconectada: hay que volver a conectarla desde la página para calcular la ganancia.")
    resultado = metricas.calcular_ganancia_real(ctx.usuario_id, ctx.cuenta_id, access_token, desde.isoformat(), hasta.isoformat())
    raw = resultado["resumen"]["raw"]
    with _conexion(ctx) as conexion:
        cobertura = costos_mod.cobertura_de_costos(conexion.cursor(), desde.isoformat(), hasta.isoformat())
    facturado = float(raw.get("facturado") or 0)
    ganancia = float(raw.get("ganancia_neta") or 0)
    datos = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "facturado": _plata(facturado), "cargos_de_mercado_libre": _plata(raw.get("comision")), "envios": _plata(raw.get("envios")),
        "publicidad": _plata(raw.get("costo_ads")), "costo_de_fabricacion": _plata(raw.get("costo_fabricacion")), "cargos_mensuales_de_mercado_libre": _plata(raw.get("cargos_fuera_de_ventas")),
        "ganancia_neta_real": _plata(ganancia), "margen_pct": round(ganancia / facturado * 100, 1) if facturado > 0 else None,
        "ventas_sin_costo_de_fabricacion_cargado_pct": cobertura["pct_sin_costo"], "origen": "pantalla Ganancia Real",
    }
    if cobertura["pct_sin_costo"] > 0:
        datos["aviso"] = "Parte de lo vendido no tiene costo de fabricación cargado: la ganancia real puede ser menor. Se carga en la pantalla Costos."
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
    datos = {
        "dias_de_historia": d["cobertura"]["dias"], "categorias_seguidas": d["cobertura"]["categorias"],
        "busquedas_en_alza_en_tus_categorias": [
            {"busqueda": b["texto"], "categoria": b["categoria_nombre"], "puesto": b["posicion"], "movimiento": b["movimiento"][1] if b["movimiento"] else None, "tus_publicaciones_con_esa_busqueda": b["tus_publicaciones"]}
            for b in d["busquedas_tuyas"][:10]],
        "aclaracion": "Mercado Libre informa el puesto de cada búsqueda, no cuántas veces se busca ni cuánto vende cada competidor.", "origen": "pantalla Mercado",
    }
    if ficha:
        datos["categoria_destacada"] = {"nombre": ficha["nombre"], "publicaciones_en_el_mercado": ficha["publicaciones"],
                                        "variacion_7_dias_pct": ficha["variacion_7"]["pct"] if ficha["variacion_7"] else None,
                                        "precio_mediano": float(ficha["muestra"]["precio_p50"]) if ficha["muestra"] and not ficha["muestra"]["vacia"] and ficha["muestra"]["precio_p50"] else None}
    return datos


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


# ── Registro ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

_PERIODO = {"dias": {"type": "integer", "description": "Los últimos N días contando hoy (1 = solo hoy, 7, 30, 90). USALO para «hoy», «esta semana», «los últimos 30 días»: no calcules fechas. Si se manda, se ignoran desde y hasta."},
            "desde": {"type": "string", "description": "Fecha inicial AAAA-MM-DD, solo para un período con fechas concretas (por ejemplo «septiembre»). Por defecto, hace 30 días."},
            "hasta": {"type": "string", "description": "Fecha final AAAA-MM-DD (por defecto, hoy)."}}

HERRAMIENTAS = {
    "ventas": {
        "descripcion": "Ventas netas (sin canceladas ni devueltas) de un período: facturado, unidades y órdenes. `agrupar`: total, dia (por día), modelo (ranking de modelos con todas sus variantes juntas: usalo para «el producto o modelo más vendido») o variante (ranking por variante: solo si preguntan por un tamaño, color u otra variante puntual).",
        "parametros": {**_PERIODO, "agrupar": {"type": "string", "enum": ["total", "dia", "modelo", "variante"]}}, "funcion": _ventas},
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

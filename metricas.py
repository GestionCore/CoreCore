"""
Ganancia Real — núcleo portado de Santi Mens, ahora con el desglose de
Publicidad (Ads) integrado y Reclamos/Devoluciones real (via
devoluciones_sync.py).
"""
from datetime import date, timedelta
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from psycopg.rows import dict_row
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
import db
import ads
import facturacion
from utils import formatear_moneda, formatear_estado_incidencia, hoy_argentina, sql_momento_argentina, limpiar_titulo_modelo, extraer_talle, nombre_tipo_publicacion

_NOMBRES_MES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def obtener_evolucion_mensual(usuario_id, cuenta_id, access_token, meses=6):
    """
    Costos vs. Resultado neto por mes calendario, últimos `meses` meses
    (incluye el actual, en curso). A propósito NO llama a
    calcular_ganancia_real una vez por mes — eso pegaría en la API de
    Ads de MeLi 6 veces con el desglose completo por ítem. En cambio:
    comisión/envío/costo de fabricación salen de UNA sola consulta SQL
    agrupada por mes, y Publicidad usa el gasto total de la cuenta por
    mes (una llamada liviana a Ads por mes, no por item).
    """
    hoy = hoy_argentina()
    inicios_mes = []
    cursor_mes = hoy.replace(day=1)
    for _ in range(meses):
        inicios_mes.append(cursor_mes)
        cursor_mes = (cursor_mes - timedelta(days=1)).replace(day=1)
    inicios_mes.reverse()  # del más viejo al más nuevo

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT to_char(date_trunc('month', v.fecha_venta), 'YYYY-MM') AS mes,
                   COALESCE(SUM(v.precio_venta * v.cantidad), 0) AS facturado,
                   COALESCE(SUM(v.cargo_venta), 0) AS comision,
                   COALESCE(SUM(v.costo_envio), 0) AS envios,
                   COALESCE(SUM(COALESCE(p.precio_costo, 0) * v.cantidad), 0) AS costo_fabricacion
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.fecha_venta BETWEEN %s AND %s
            GROUP BY 1
        """, (inicios_mes[0].strftime("%Y-%m-%d"), hoy.strftime("%Y-%m-%d")))
        por_mes = {f["mes"]: f for f in cursor.fetchall()}

    gasto_ads_por_mes = {}
    try:
        advertiser_id = ads.obtener_advertiser_id(access_token, cuenta_id)
        if advertiser_id:
            # Las 6 llamadas a Ads son independientes entre sí (un mes no
            # depende del otro) — pedirlas en paralelo en vez de una por
            # una es la diferencia entre ~6 x 300ms y ~300ms totales.
            # Mismo patrón que ya usa ads.obtener_serie_diaria_ads.
            def _gasto_del_mes(inicio):
                fin = min((inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), hoy)
                etiqueta = inicio.strftime("%Y-%m")
                gasto = ads.obtener_gasto_ads_total_periodo(
                    access_token, advertiser_id, inicio.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")
                )
                return etiqueta, (gasto or 0.0)

            with ThreadPoolExecutor(max_workers=6) as pool:
                for etiqueta, gasto in pool.map(_gasto_del_mes, inicios_mes):
                    gasto_ads_por_mes[etiqueta] = gasto
    except Exception as e:
        print(f"[Metricas] ⚠️ Error trayendo evolución de Ads: {e}")

    serie = []
    for inicio in inicios_mes:
        etiqueta = inicio.strftime("%Y-%m")
        fila = por_mes.get(etiqueta)
        facturado = float(fila["facturado"]) if fila else 0.0
        comision = float(fila["comision"]) if fila else 0.0
        envios = float(fila["envios"]) if fila else 0.0
        costo_fabricacion = float(fila["costo_fabricacion"]) if fila else 0.0
        costos_totales = round(comision + envios + costo_fabricacion + gasto_ads_por_mes.get(etiqueta, 0.0), 2)
        serie.append({
            "mes": etiqueta, "mes_label": _NOMBRES_MES_CORTOS[inicio.month - 1],
            "facturado": round(facturado, 2), "costos": costos_totales,
            "resultado_neto": round(facturado - costos_totales, 2),
        })
    return serie


def obtener_analitica_clientes(usuario_id, fecha_desde, fecha_hasta, cuenta_id=None):
    """
    Retención y forma de pago, a nivel de ORDEN (no de fila de venta —
    una orden con 3 ítems son 3 filas en `ventas` pero 1 sola compra).
    Todo queda acotado al período elegido en la página, no es
    histórico de vida del cliente — más simple y consistente con el
    resto de Ganancia Real, que también es por período.
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT id_orden, comprador_nickname, MAX(cuotas) AS cuotas
            FROM ventas
            WHERE fecha_venta BETWEEN %s AND %s
              AND eliminado_en IS NULL AND origen = 'meli' AND comprador_nickname IS NOT NULL
            GROUP BY id_orden, comprador_nickname
        """, (fecha_desde, fecha_hasta))
        ordenes = cursor.fetchall()

    if not ordenes:
        return None

    ordenes_por_cliente = {}
    for o in ordenes:
        ordenes_por_cliente[o["comprador_nickname"]] = ordenes_por_cliente.get(o["comprador_nickname"], 0) + 1

    total_clientes = len(ordenes_por_cliente)
    clientes_repiten = sum(1 for c in ordenes_por_cliente.values() if c >= 2)

    conteo_por_veces = {1: 0, 2: 0, 3: 0}
    conteo_4_mas = 0
    for c in ordenes_por_cliente.values():
        if c in conteo_por_veces:
            conteo_por_veces[c] += 1
        else:
            conteo_4_mas += 1
    distribucion_frecuencia = [
        {"veces": "1 vez", "cantidad": conteo_por_veces[1]},
        {"veces": "2 veces", "cantidad": conteo_por_veces[2]},
        {"veces": "3 veces", "cantidad": conteo_por_veces[3]},
        {"veces": "4 o más", "cantidad": conteo_4_mas},
    ]

    ordenes_con_dato_cuotas = [o for o in ordenes if o["cuotas"] is not None]
    ordenes_en_cuotas = [o for o in ordenes_con_dato_cuotas if o["cuotas"] > 1]
    ordenes_contado = [o for o in ordenes_con_dato_cuotas if o["cuotas"] <= 1]

    conteo_cuotas = {}
    for o in ordenes_en_cuotas:
        conteo_cuotas[o["cuotas"]] = conteo_cuotas.get(o["cuotas"], 0) + 1
    distribucion_cuotas = sorted(
        [{"cuotas": k, "cantidad": v} for k, v in conteo_cuotas.items()], key=lambda x: x["cuotas"]
    )

    return {
        "clientes_distintos": total_clientes,
        "clientes_repiten": clientes_repiten,
        "pct_repiten": round(clientes_repiten / total_clientes * 100, 1) if total_clientes else 0,
        "distribucion_frecuencia": distribucion_frecuencia,
        "total_ordenes": len(ordenes),
        "ordenes_con_dato_cuotas": len(ordenes_con_dato_cuotas),
        "cant_ordenes_cuotas": len(ordenes_en_cuotas),
        "cant_ordenes_contado": len(ordenes_contado),
        "pct_cuotas": round(len(ordenes_en_cuotas) / len(ordenes_con_dato_cuotas) * 100, 1) if ordenes_con_dato_cuotas else None,
        "pct_contado": round(len(ordenes_contado) / len(ordenes_con_dato_cuotas) * 100, 1) if ordenes_con_dato_cuotas else None,
        "distribucion_cuotas": distribucion_cuotas,
        "cuota_mas_elegida": max(distribucion_cuotas, key=lambda x: x["cantidad"])["cuotas"] if distribucion_cuotas else None,
    }


def _obtener_comparacion_periodo_anterior(cursor, fecha_desde, fecha_hasta):
    """
    "vs. período anterior" — pedido explícito: si el rango elegido son 14
    días, comparar contra los 14 días inmediatamente anteriores; si es un
    mes calendario (el default de la pantalla), contra el mes anterior.
    No hace falta lógica especial para eso: alcanza con calcular el largo
    real del rango elegido (en días) y correr esa misma cantidad de días
    hacia atrás — funciona igual para cualquier rango.

    A propósito NO repite el cálculo completo de Ganancia Real (que
    llama a la API de Ads) para el período anterior — solo una suma
    liviana de facturación/unidades/órdenes contra `ventas`, para no
    duplicar llamadas a MeLi ni volver esto pesado.
    """
    desde_dt = date.fromisoformat(str(fecha_desde))
    hasta_dt = date.fromisoformat(str(fecha_hasta))
    largo_dias = (hasta_dt - desde_dt).days + 1
    hasta_anterior = desde_dt - timedelta(days=1)
    desde_anterior = hasta_anterior - timedelta(days=largo_dias - 1)

    # Alias explícitos, a propósito: este cursor usa row_factory=dict_row
    # (llega armado así desde calcular_ganancia_real), y sin alias las dos
    # columnas COALESCE(...) reciben el mismo nombre por defecto de
    # Postgres — el dict resultante termina con 2 claves en vez de 3 (la
    # segunda pisa a la primera), y el unpacking de abajo revienta con
    # "not enough values to unpack". Ya me había pasado una vez en este
    # mismo archivo con otra query; se me escapó acá al escribirla de nuevo.
    cursor.execute("""
        SELECT COALESCE(SUM(precio_venta * cantidad), 0) AS facturado,
               COALESCE(SUM(cantidad), 0) AS unidades,
               COUNT(DISTINCT id_orden) AS ordenes
        FROM ventas WHERE fecha_venta BETWEEN %s AND %s
    """, (desde_anterior, hasta_anterior))
    fila = cursor.fetchone()
    facturado_ant = float(fila["facturado"] or 0)
    unidades_ant = fila["unidades"]
    ordenes_ant = fila["ordenes"]

    return {
        "desde": desde_anterior.isoformat(), "hasta": hasta_anterior.isoformat(),
        "facturado_formateado": formatear_moneda(facturado_ant), "unidades": unidades_ant, "ordenes": ordenes_ant,
        "facturado_raw": facturado_ant,
    }


def _fila_consolidada(cp):
    """Una fila de la tabla de modelos a partir de sus TOTALES (unidades, facturado, costos): todo se calcula como total ÷ unidades (promedio ponderado)."""
    u = cp["unidades"]
    p_prom = cp["facturado"] / u if u > 0 else 0.0
    c_com_u = cp["cargos_meli"] / u if u > 0 else 0.0
    c_env_u = cp["envios"] / u if u > 0 else 0.0
    c_ads_u = cp["ads"] / u if u > 0 else 0.0
    c_fab_u = cp["costo_fab"] / u if u > 0 else 0.0
    neto_u = p_prom - c_com_u - c_env_u - c_ads_u - c_fab_u
    return {
        "titulo": cp["titulo"], "thumbnail": cp["thumbnail"], "unidades": u, "facturado_raw": cp["facturado"],
        "precio_promedio": formatear_moneda(p_prom), "total_facturado": formatear_moneda(cp["facturado"]),
        "cargo_u": formatear_moneda(c_com_u), "envio_u": formatear_moneda(c_env_u), "ads_u": formatear_moneda(c_ads_u),
        "costo_u": formatear_moneda(c_fab_u), "neto_u": formatear_moneda(neto_u), "neto_total": formatear_moneda(neto_u * u),
        "raw": {
            "precio_promedio": round(p_prom, 2), "total_facturado": round(cp["facturado"], 2),
            "cargo_u": round(c_com_u, 2), "envio_u": round(c_env_u, 2), "ads_u": round(c_ads_u, 2),
            "costo_u": round(c_fab_u, 2), "neto_u": round(neto_u, 2), "neto_total": round(neto_u * u, 2),
        },
    }


def consolidar_por_modelo(por_publicacion):
    """
    Une las publicaciones de un mismo modelo (los talles/variantes son publicaciones distintas en Mercado Libre) en una sola fila, sumando TOTALES y
    recién después sacando los promedios por unidad: es el promedio ponderado real que exige el proyecto, nunca un promedio simple de talles.
    `por_publicacion` es {id_meli: {titulo, thumbnail, unidades, facturado, costo_fab, cargos_meli, envios, ads}}; `ads` es el total de publicidad de
    esa publicación en el período. Devuelve las filas por modelo (la de mayor facturación primero), cada una con `variantes` (el detalle por publicación).
    """
    modelos = {}
    for id_meli, p in por_publicacion.items():
        nombre = limpiar_titulo_modelo(p["titulo"]) or p["titulo"] or "Sin nombre"
        m = modelos.setdefault(nombre.lower(), {"titulo": nombre, "thumbnail": None, "mejor": -1.0, "unidades": 0, "facturado": 0.0, "costo_fab": 0.0,
                                                "cargos_meli": 0.0, "envios": 0.0, "ads": 0.0, "variantes": []})
        for campo in ("unidades", "facturado", "costo_fab", "cargos_meli", "envios", "ads"):
            m[campo] += p[campo]
        if p["facturado"] > m["mejor"]:                       # la foto es la de la publicación del modelo que más facturó
            m["mejor"], m["thumbnail"] = p["facturado"], p["thumbnail"]
        talle = extraer_talle(p["titulo"])
        fila = _fila_consolidada(p)
        fila.update({"id_meli": id_meli, "talle": None if talle == "Único" else talle, "tipo": nombre_tipo_publicacion(p.get("tipo"))})
        m["variantes"].append(fila)
    filas = []
    for m in modelos.values():
        fila = _fila_consolidada(m)
        fila["variantes"] = sorted(m["variantes"], key=lambda v: -v["facturado_raw"])
        filas.append(fila)
    filas.sort(key=lambda c: -c["facturado_raw"])
    return filas


def calcular_ganancia_real(usuario_id, cuenta_id, access_token, fecha_desde, fecha_hasta):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        comparacion_anterior = _obtener_comparacion_periodo_anterior(cursor, fecha_desde, fecha_hasta)

        cursor.execute(f"""
            SELECT id_orden, id_meli, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, id_variante, envio_estado,
                   COALESCE(costo_flex, 0) AS costo_flex, retenciones, neto_recibido, COALESCE(financiacion, 0) AS financiacion, cuotas,
                   {sql_momento_argentina()} AS momento
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s ORDER BY fecha_venta DESC
        """, (fecha_desde, fecha_hasta))
        ventas_db = cursor.fetchall()

        cursor.execute("SELECT id_variante, talle, color FROM productos_variantes")
        # El cursor usa row_factory=dict_row (filas como {"id_variante": ...},
        # no tuplas) — indexar con r[0]/r[1] tira KeyError apenas hay alguna
        # fila. Antes nunca se notaba porque productos_variantes estaba
        # vacía (bloqueada por el bug de RLS sin política).
        info_variantes = {r["id_variante"]: (r["talle"], r["color"]) for r in cursor.fetchall()}

        cursor.execute("SELECT id_meli, precio_costo, thumbnail, listing_type_id FROM productos_padre")
        # dict(cursor.fetchall()) tampoco sirve con dict_row: cada fila ya es
        # un dict de 2 claves ("id_meli", "precio_costo"), y dict() sobre una
        # lista de esos termina interpretando cada fila como el PAR
        # (clave, valor) = (nombres de columna) en vez de (id_meli, costo) —
        # no tira error, pero arma costos_por_item con basura, corrompiendo
        # el costo de fabricación de Ganancia Neta Real en silencio.
        filas_productos = cursor.fetchall()
        costos_por_item = {r["id_meli"]: r["precio_costo"] for r in filas_productos}
        thumbnails_por_item = {r["id_meli"]: r["thumbnail"] for r in filas_productos}
        tipos_por_item = {r["id_meli"]: r["listing_type_id"] for r in filas_productos}

        cursor.execute("""
            SELECT tipo, motivo, estado, id_orden, fecha, COALESCE(monto_retenido, 0.0) AS monto_retenido, afecta_reputacion
            FROM incidencias_posventa WHERE fecha BETWEEN %s AND %s ORDER BY fecha DESC
        """, (fecha_desde, fecha_hasta))
        incidencias_db = cursor.fetchall()

        # Ventas cuya orden se canceló o reembolsó después de sincronizarla: ya no cuentan (ver ventas_sync.retirar_ventas_canceladas)
        cursor.execute("""
            SELECT COUNT(DISTINCT id_orden) AS ordenes, COALESCE(SUM(monto), 0) AS monto
            FROM ventas_retiradas WHERE (fila->>'fecha_venta')::date BETWEEN %s AND %s
        """, (fecha_desde, fecha_hasta))
        retiradas = cursor.fetchone()

    unidades_por_item = {}
    for v in ventas_db:
        unidades_por_item[v["id_meli"]] = unidades_por_item.get(v["id_meli"], 0) + v["cantidad"]

    # Publicidad — si no hay cuenta de anunciante o falla la consulta,
    # seguimos igual mostrando el resto de los números (nunca romper la
    # página entera por esto).
    costos_ads_por_item = {}
    ads_disponible = False
    gasto_ads_total_periodo = None
    try:
        advertiser_id = ads.obtener_advertiser_id(access_token, cuenta_id)
        if advertiser_id:
            ads_disponible = True
            ids_con_ventas = list(unidades_por_item.keys())
            costos_ads_por_item = ads.obtener_costos_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_con_ventas)
            gasto_ads_total_periodo = ads.obtener_gasto_ads_total_periodo(access_token, advertiser_id, fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Metricas] ⚠️ Error consultando Ads: {e}")

    ventas_procesadas = []
    total_facturado = 0.0
    total_ganancia_neta_real = 0.0
    total_costo_fabricacion = 0.0
    total_costo_ads = 0.0
    total_comision = 0.0
    total_envio_real = 0.0
    total_retenciones = 0.0
    # Conciliación: contra lo que Mercado Libre DEPOSITÓ de verdad (solo las ventas de las que ya tenemos el pago)
    conc_ventas = conc_facturado = conc_depositado = conc_esperado = 0.0
    consolidado_dict = {}

    for v in ventas_db:
        id_orden, id_meli, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, id_var, envio_estado = (
            v["id_orden"], v["id_meli"], v["titulo"], v["cantidad"], v["precio_venta"],
            v["cargo_venta"], v["costo_envio"], v["fecha_venta"], v["id_variante"], v["envio_estado"]
        )
        cargo_venta = float(cargo_venta or 0.0)
        costo_envio = float(costo_envio or 0.0)

        costo_fabrica_unitario = float(costos_por_item.get(id_meli) or 0.0)
        costo_fabricacion_total = costo_fabrica_unitario * cantidad

        unidades_item = unidades_por_item.get(id_meli, 0)
        costo_ads_total_item = costos_ads_por_item.get(id_meli, 0.0)
        costo_ads_unitario = (costo_ads_total_item / unidades_item) if unidades_item > 0 else 0.0
        costo_ads_fila = round(costo_ads_unitario * cantidad, 2)

        ingreso_bruto_operacion = float(precio_venta) * cantidad
        ganancia_neta = round(ingreso_bruto_operacion - cargo_venta - costo_envio - costo_ads_fila - costo_fabricacion_total, 2)

        total_facturado += ingreso_bruto_operacion
        total_ganancia_neta_real += ganancia_neta
        total_costo_fabricacion += costo_fabricacion_total
        total_costo_ads += costo_ads_fila
        total_comision += cargo_venta
        total_envio_real += costo_envio
        retenciones_fila = float(v["retenciones"] or 0.0)
        total_retenciones += retenciones_fila
        if v["neto_recibido"] is not None:
            # Lo que MeLi descuenta al depositar: comisión y cupones, envío (sin el costo Flex, que lo cobra la logística propia) y retenciones
            conc_ventas += 1
            conc_facturado += ingreso_bruto_operacion
            conc_depositado += float(v["neto_recibido"])
            conc_esperado += ingreso_bruto_operacion - cargo_venta - (costo_envio - float(v["costo_flex"])) - retenciones_fila

        talle_real, color_real = info_variantes.get(id_var, ("Único", "Único"))
        talle_str = talle_real if (not color_real or color_real == "Único") else f"{talle_real} / {color_real}"

        ventas_procesadas.append({
            "id_orden": id_orden, "id_meli": id_meli, "titulo": titulo, "talle": talle_str, "cantidad": cantidad,
            "precio_venta": formatear_moneda(ingreso_bruto_operacion), "cargo_venta": formatear_moneda(cargo_venta),
            "costo_envio": formatear_moneda(costo_envio), "envio_pendiente": (envio_estado == "pendiente"),
            "costo_ads": formatear_moneda(costo_ads_fila), "costo_fabricacion": formatear_moneda(costo_fabricacion_total),
            "ganancia_neta_formateada": formatear_moneda(ganancia_neta), "es_negativo": ganancia_neta < 0,
            "fecha": fecha_venta.strftime("%Y-%m-%d") if hasattr(fecha_venta, "strftime") else fecha_venta,
            "momento": v["momento"].isoformat(timespec="minutes") if v.get("momento") else None,      # fecha y hora argentina ("2026-10-02T10:35")
            # Numeros reales (no texto formateado) para el export a Excel.
            "raw": {
                "precio_venta": round(ingreso_bruto_operacion, 2), "cargo_venta": round(cargo_venta, 2),
                "costo_envio": round(costo_envio, 2), "costo_ads": round(costo_ads_fila, 2),
                "costo_fabricacion": round(costo_fabricacion_total, 2), "ganancia_neta": ganancia_neta,
            }
        })

        if id_meli not in consolidado_dict:
            consolidado_dict[id_meli] = {"titulo": titulo, "thumbnail": thumbnails_por_item.get(id_meli), "tipo": tipos_por_item.get(id_meli), "unidades": 0, "facturado": 0.0, "costo_fab": 0.0, "cargos_meli": 0.0, "envios": 0.0, "ads": costo_ads_total_item}
        consolidado_dict[id_meli]["unidades"] += cantidad
        consolidado_dict[id_meli]["facturado"] += ingreso_bruto_operacion
        consolidado_dict[id_meli]["costo_fab"] += costo_fabricacion_total
        consolidado_dict[id_meli]["cargos_meli"] += cargo_venta
        consolidado_dict[id_meli]["envios"] += costo_envio

    lista_consolidados = consolidar_por_modelo(consolidado_dict)

    # Cargos mensuales de Mercado Libre que no están en ninguna venta (eShop, almacenamiento y retiros de FULL, reputación, devoluciones): son plata que sale del
    # negocio y a los vendedores se les acredita la diferencia, así que se descuentan de la ganancia repartidos por día. Si Mercado Libre no responde, la
    # pantalla sigue con las ventas y lo avisa (`completo`), nunca se rompe.
    cargos_fuera_de_ventas = {"total": 0.0, "items": [], "completo": False}
    try:
        cargos_fuera_de_ventas = facturacion.cargos_fuera_de_ventas(usuario_id, cuenta_id, access_token, fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Metricas] ⚠️ No se pudieron traer los cargos mensuales de Mercado Libre: {e}")
    total_fijos_meli = float(cargos_fuera_de_ventas["total"])
    ganancia_neta_ventas = total_ganancia_neta_real                # la suma de cada venta (lo que muestra la tabla)
    total_ganancia_neta_real = round(ganancia_neta_ventas - total_fijos_meli, 2)

    # Lo que cuesta ofrecer cuotas sin interés: Mercado Libre cobra un cargo de financiación POR PUBLICACIÓN (un % casi fijo del precio) en cada
    # venta, aunque el comprador pague de contado. Ya está dentro de los cargos de MeLi; acá se separa para poder decidir publicación por publicación.
    por_publicacion = {}
    for v in ventas_db:
        p = por_publicacion.setdefault(v["id_meli"], {"id_meli": v["id_meli"], "titulo": v["titulo"], "thumbnail": thumbnails_por_item.get(v["id_meli"]),
                                                      "ventas": 0, "facturado": 0.0, "financiacion": 0.0})
        p["ventas"] += 1
        p["facturado"] += float(v["precio_venta"]) * v["cantidad"]
        p["financiacion"] += float(v["financiacion"])
    total_financiacion = sum(p["financiacion"] for p in por_publicacion.values())
    facturado_periodo = sum(p["facturado"] for p in por_publicacion.values())
    resumen_financiacion = None
    if total_financiacion > 0:
        con_cargo = sorted((p for p in por_publicacion.values() if p["financiacion"] > 0), key=lambda p: -p["financiacion"])
        for p in con_cargo:
            p["pct"] = round(p["financiacion"] / p["facturado"] * 100, 1) if p["facturado"] else 0.0
            p["financiacion"] = round(p["financiacion"], 2)
        resumen_financiacion = {
            "total": formatear_moneda(total_financiacion), "total_raw": round(total_financiacion, 2),
            "pct_facturado": round(total_financiacion / facturado_periodo * 100, 1) if facturado_periodo else 0.0,
            "publicaciones": con_cargo[:12], "publicaciones_total": len(con_cargo),
            "sin_cargo": sum(1 for p in por_publicacion.values() if p["financiacion"] <= 0),
        }

    total_devoluciones = sum(1 for inc in incidencias_db if inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower())
    total_cancelaciones = sum(1 for inc in incidencias_db if "cancel" in (inc["tipo"] or "").lower())
    def _es_reclamo(inc):
        return inc["tipo"] in ("claim", "mediation") or "reclamo" in (inc["tipo"] or "").lower()

    def _afecta_reputacion(inc):
        # Mercado Libre dice si cuenta contra la reputación; mientras no se sabe (NULL) se trata como que sí, por prudencia
        return inc["afecta_reputacion"] in (None, "affected")
    total_reclamos = sum(1 for inc in incidencias_db if _es_reclamo(inc) and _afecta_reputacion(inc))
    reclamos_sin_impacto = sum(1 for inc in incidencias_db if _es_reclamo(inc) and not _afecta_reputacion(inc))
    total_dinero_retenido = sum(float(inc["monto_retenido"]) for inc in incidencias_db)

    conteo_motivos = {}
    for inc in incidencias_db:
        es_devolucion = inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower()
        if es_devolucion:
            motivo_legible = inc["motivo"] or "Sin motivo especificado"
            conteo_motivos[motivo_legible] = conteo_motivos.get(motivo_legible, 0) + 1
    ranking_motivos_devolucion = sorted(
        [{"motivo": m, "cantidad": c} for m, c in conteo_motivos.items()], key=lambda x: -x["cantidad"]
    )[:5]

    resumen_posventa = {
        "devoluciones": total_devoluciones, "cancelaciones": total_cancelaciones, "reclamos": total_reclamos, "reclamos_sin_impacto": reclamos_sin_impacto,
        "financiacion": resumen_financiacion, "ventas_retiradas": int(retiradas["ordenes"] or 0), "monto_retirado": formatear_moneda(retiradas["monto"]),
        "dinero_retenido": formatear_moneda(total_dinero_retenido), "dinero_retenido_monto": round(total_dinero_retenido, 2),
        "ranking_motivos_devolucion": ranking_motivos_devolucion,
        "lista": [
            {
                "tipo": "DEVOLUCIÓN" if (inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower()) else ("CANCELACIÓN" if "cancel" in (inc["tipo"] or "").lower() else "RECLAMO"),
                "sin_impacto": not _afecta_reputacion(inc),
                "motivo": inc["motivo"], "estado": formatear_estado_incidencia(inc["estado"]), "id_orden": inc["id_orden"],
                "fecha": inc["fecha"].strftime("%Y-%m-%d") if hasattr(inc["fecha"], "strftime") else inc["fecha"],
                "monto_retenido": formatear_moneda(inc["monto_retenido"]),
                "link": f"https://myaccount.mercadolibre.com.ar/sales/{inc['id_orden']}/detail"
            }
            for inc in incidencias_db
        ]
    }

    comparacion_anterior["variacion_facturado_pct"] = (
        round(((total_facturado - comparacion_anterior["facturado_raw"]) / comparacion_anterior["facturado_raw"]) * 100, 1)
        if comparacion_anterior["facturado_raw"] else None
    )

    return {
        "ventas": ventas_procesadas,
        "consolidados": lista_consolidados,
        "ads_disponible": ads_disponible,
        "gasto_ads_total_periodo": gasto_ads_total_periodo,
        "posventa": resumen_posventa,
        "comparacion_anterior": comparacion_anterior,
        "cargos_fuera_de_ventas": cargos_fuera_de_ventas,
        "resumen": {
            "facturado": formatear_moneda(total_facturado),
            "ganancia_neta": formatear_moneda(total_ganancia_neta_real),
            "ganancia_neta_negativa": total_ganancia_neta_real < 0,
            "comision": formatear_moneda(total_comision),
            "envios": formatear_moneda(total_envio_real),
            "costo_ads": formatear_moneda(total_costo_ads),
            "costo_fabricacion": formatear_moneda(total_costo_fabricacion),
            "cargos_fuera_de_ventas": formatear_moneda(total_fijos_meli),
            # Version sin formatear (numeros de verdad, no texto "1.234,56")
            # para el export a Excel — openpyxl necesita numeros reales para
            # que las columnas se puedan sumar/graficar del lado de Excel.
            "raw": {
                # ganancia_neta: la real, ya sin los cargos mensuales de MeLi; ganancia_neta_ventas: la suma de lo que dejó cada venta (con la que se compara un día contra el promedio)
                "facturado": round(total_facturado, 2), "ganancia_neta": round(total_ganancia_neta_real, 2), "ganancia_neta_ventas": round(ganancia_neta_ventas, 2),
                "comision": round(total_comision, 2), "envios": round(total_envio_real, 2),
                "costo_ads": round(total_costo_ads, 2), "costo_fabricacion": round(total_costo_fabricacion, 2),
                "cargos_fuera_de_ventas": round(total_fijos_meli, 2),
                # Retenciones de impuestos (IIBB, SIRTAC...): MeLi las descuenta al depositar; NO restan de la ganancia (se descuentan después de tus impuestos)
                "retenciones": round(total_retenciones, 2),
                "conciliacion": {
                    "ventas": int(conc_ventas), "cobertura_pct": round(conc_ventas / len(ventas_db) * 100) if ventas_db else 0,
                    "facturado": round(conc_facturado, 2), "depositado": round(conc_depositado, 2), "esperado": round(conc_esperado, 2),
                    "diferencia": round(conc_depositado - conc_esperado, 2),
                    "coincide_pct": round(100 - abs(conc_depositado - conc_esperado) / conc_depositado * 100, 1) if conc_depositado else None,
                },
            }
        }
    }


def generar_excel_balance(datos, fecha_desde, fecha_hasta):
    """
    Balance de rentabilidad del período como .xlsx — item pendiente #3
    del brainstorm original. Tres hojas: Resumen (los mismos totales de
    la pantalla), Consolidado por modelo (promedio ponderado real, igual
    que en pantalla — nunca promedio simple de talles) y Detalle de
    ventas fila por fila. Devuelve un BytesIO listo para send_file.
    """
    wb = Workbook()
    azul_header = Font(bold=True, color="FFFFFF")
    fondo_header = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")

    def _armar_header(ws, columnas):
        ws.append(columnas)
        for celda in ws[1]:
            celda.font = azul_header
            celda.fill = fondo_header

    ws_resumen = wb.active
    ws_resumen.title = "Resumen"
    ws_resumen.append(["Balance de Rentabilidad — Ganancia Real"])
    ws_resumen["A1"].font = Font(bold=True, size=14)
    ws_resumen.append([f"Período: {fecha_desde} al {fecha_hasta}"])
    ws_resumen.append([])
    r = datos["resumen"]["raw"]
    _armar_header(ws_resumen, ["Concepto", "Monto ($)"])
    for etiqueta, clave in [
        ("Facturación", "facturado"), ("Cargos MeLi", "comision"), ("Envíos", "envios"),
        ("Publicidad", "costo_ads"), ("Costo de Fabricación", "costo_fabricacion"),
        ("Cargos mensuales de MeLi (eShop, FULL, devoluciones…)", "cargos_fuera_de_ventas"),
        ("Ganancia Neta Real", "ganancia_neta"),
    ]:
        ws_resumen.append([etiqueta, r.get(clave, 0)])
    ws_resumen.append([])
    p = datos["posventa"]
    ws_resumen.append(["Devoluciones", p["devoluciones"]])
    ws_resumen.append(["Cancelaciones", p["cancelaciones"]])
    ws_resumen.append(["Reclamos", p["reclamos"]])
    ws_resumen.append(["Dinero retenido ($)", p["dinero_retenido_monto"]])
    for col, ancho in [("A", 26), ("B", 16)]:
        ws_resumen.column_dimensions[col].width = ancho

    ws_modelos = wb.create_sheet("Consolidado por modelo")
    _armar_header(ws_modelos, ["Modelo", "Unidades", "Precio promedio", "Facturado", "Cargo MeLi (u)", "Envío (u)", "Ads (u)", "Costo (u)", "Neto (u)", "Neto total"])
    for c in datos["consolidados"]:
        cr = c["raw"]
        ws_modelos.append([
            c["titulo"], c["unidades"], cr["precio_promedio"], cr["total_facturado"],
            cr["cargo_u"], cr["envio_u"], cr["ads_u"], cr["costo_u"], cr["neto_u"], cr["neto_total"]
        ])
    ws_modelos.column_dimensions["A"].width = 45
    for col in "BCDEFGHIJ":
        ws_modelos.column_dimensions[col].width = 15

    ws_ventas = wb.create_sheet("Detalle de ventas")
    _armar_header(ws_ventas, ["Fecha", "Orden", "Producto", "Talle", "Cantidad", "Precio venta", "Cargo MeLi", "Envío", "Ads", "Costo fabricación", "Ganancia neta"])
    for v in datos["ventas"]:
        vr = v["raw"]
        ws_ventas.append([
            v["fecha"], v["id_orden"], v["titulo"], v["talle"], v["cantidad"],
            vr["precio_venta"], vr["cargo_venta"], vr["costo_envio"], vr["costo_ads"],
            vr["costo_fabricacion"], vr["ganancia_neta"]
        ])
    ws_ventas.column_dimensions["C"].width = 45
    for col in "ABDEFGHIJK":
        ws_ventas.column_dimensions[col].width = 14

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

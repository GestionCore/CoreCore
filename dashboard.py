"""
Dashboard personalizable — portado de Santi Mens. Nota real de traducción:
el original usaba `fecha_venta LIKE 'YYYY-MM-DD%'` para matchear "hoy",
porque en SQLite fecha_venta a veces llevaba el timestamp completo como
texto. Acá fecha_venta es un DATE limpio (sin hora), así que un simple
`= %s` alcanza y es más correcto.
"""
from datetime import datetime, timedelta, timezone
import re
import db
import analisis_stock
import salud_cuenta
import resumen_semanal
from utils import formatear_moneda, limpiar_titulo_modelo


def _detalle_venta(titulo):
    modelo = limpiar_titulo_modelo(titulo)
    match_talle = re.search(r'\b(XXXL|XXL|XL|L|M|S|\d+)\b', titulo, re.IGNORECASE)
    talle = match_talle.group(0).upper() if match_talle else "Único"
    return f"{modelo} (Talle {talle})"


def obtener_ventas_hoy(usuario_id, cuenta_id=None):
    arg_now = datetime.now(timezone.utc) - timedelta(hours=3)
    hoy_local = arg_now.strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT titulo, id_variante, cantidad, precio_venta, hora_venta, id_orden, id_meli
            FROM ventas WHERE fecha_venta = %s ORDER BY id DESC
        """, (hoy_local,))
        ventas_hoy = cursor.fetchall()

        cursor.execute("""
            SELECT COALESCE(SUM(precio_venta * cantidad), 0), COALESCE(SUM(cantidad), 0), COUNT(DISTINCT id_orden)
            FROM ventas WHERE fecha_venta = %s
        """, (hoy_local,))
        facturado_hoy, unidades_hoy, ordenes_hoy = cursor.fetchone()

    lista_ventas = []
    for titulo, id_variante, cant, precio_unitario, hora_venta, id_orden, id_meli in ventas_hoy:
        hora_str = hora_venta.strftime("%H:%M") if hasattr(hora_venta, "strftime") else (hora_venta or arg_now.strftime("%H:%M"))
        lista_ventas.append({
            "id_venta": f"{id_orden}_{id_variante}", "id_orden": id_orden, "titulo": _detalle_venta(titulo),
            "cantidad": cant, "precio": formatear_moneda(cant * float(precio_unitario)), "hora": hora_str,
            "link_meli": f"https://myaccount.mercadolibre.com.ar/sales/{id_orden}/detail"
        })

    return {
        "facturado_hoy": formatear_moneda(facturado_hoy), "unidades_hoy": unidades_hoy,
        "ordenes_hoy": ordenes_hoy, "ultimas_ventas": lista_ventas
    }


def obtener_ventas_por_provincia(usuario_id, cuenta_id=None, dias=30):
    """
    Ranking de provincias por facturación (F1). `provincia` sale del
    envío de MeLi — ventas manuales o ventas ya sincronizadas antes de
    que se empezara a guardar este dato quedan afuera del ranking
    (NULL), no se cuentan como "Sin dato" para no inflar ninguna barra.
    """
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT provincia, COUNT(DISTINCT id_orden) AS ventas, COALESCE(SUM(precio_venta * cantidad), 0) AS facturado
            FROM ventas
            WHERE fecha_venta >= %s AND origen = 'meli' AND provincia IS NOT NULL AND eliminado_en IS NULL
            GROUP BY provincia
            ORDER BY facturado DESC
        """, (desde,))
        filas = cursor.fetchall()

    if not filas:
        return None
    total_facturado = sum(float(f[2]) for f in filas)
    return [
        {
            "provincia": f[0], "ventas": int(f[1]), "facturado_formateado": formatear_moneda(f[2]),
            "pct": round(float(f[2]) / total_facturado * 100, 1) if total_facturado else 0,
        }
        for f in filas
    ]


def obtener_ticker(usuario_id, cuenta_id=None):
    # Mismo criterio que obtener_ventas_hoy: "hoy" es el día en Argentina
    # (UTC-3), no el del reloj del sistema donde corra el proceso — si
    # alguna vez esto corre en un servidor en UTC en vez de en la PC del
    # usuario, datetime.now() a secas daría el día equivocado justo en las
    # horas cercanas a la medianoche.
    arg_now = datetime.now(timezone.utc) - timedelta(hours=3)
    hoy = arg_now.strftime("%Y-%m-%d")
    manana = (arg_now + timedelta(days=1)).strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0), COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta = %s", (hoy,))
        fact_hoy, ord_hoy = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(monto_liberacion), 0) FROM ventas WHERE fecha_liberacion = %s", (manana,))
        liberacion_manana = cursor.fetchone()[0] or 0.0

        cursor.execute("""
            SELECT titulo, cantidad, precio_venta, hora_venta FROM ventas
            WHERE fecha_venta = %s ORDER BY hora_venta DESC LIMIT 8
        """, (hoy,))
        ventas_hoy_detalle = []
        for t, c, p, h in cursor.fetchall():
            hora_str = h.strftime("%H:%M") if hasattr(h, "strftime") else (h or "")[:5]
            ventas_hoy_detalle.append({"titulo": t, "cantidad": c, "precio_formateado": formatear_moneda(p), "hora": hora_str})

        # Reclamos y devoluciones se cuentan POR SEPARADO (lo pidió el usuario: una devolución simple no es un
        # reclamo). Solo un reclamo real ('claim') puede afectar la reputación; una devolución es gestión del día a día.
        # Las cancelaciones no son nada que el vendedor tenga que resolver.
        cursor.execute("""
            SELECT COALESCE(SUM((tipo = 'claim')::int), 0), COALESCE(SUM((tipo = 'return')::int), 0)
            FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved')
        """)
        incidencias_activas, devoluciones_activas = (int(x or 0) for x in cursor.fetchone())

        salud = salud_cuenta.calcular_score_salud(cursor)

        # Ojo: si la migración de racha_dias todavía no corrió, esto
        # tira error — a propósito no hay try/except acá adentro: un
        # error de SQL deja la transacción en estado "aborted", y el
        # commit() del `with` de más arriba fallaría igual al salir, así
        # que atajarlo acá no evita nada, solo lo esconde peor.
        racha_dias = 0
        if cuenta_id:
            cursor.execute("SELECT racha_dias FROM cuentas_meli WHERE id = %s", (cuenta_id,))
            fila_racha = cursor.fetchone()
            racha_dias = (fila_racha[0] or 0) if fila_racha else 0

    return {
        "ventas_hoy": ord_hoy, "facturado_hoy": formatear_moneda(fact_hoy),
        "liberacion_manana": formatear_moneda(liberacion_manana), "bridge_activo": False,
        "incidencias_activas": incidencias_activas, "devoluciones_activas": devoluciones_activas, "salud_score": salud["score"], "racha_dias": racha_dias,
        "salud_etiqueta": salud["etiqueta"], "salud_detalle": salud["detalle"],
        "ventas_hoy_detalle": ventas_hoy_detalle
    }


def obtener_tendencia_ventas(usuario_id, cuenta_id=None, dias=14):
    """
    Facturación por día de los últimos N días — para el gráfico de
    tendencia del Dashboard. Pedido explícito del usuario ("quiero
    gráficos, no solo cuadraditos"): esto no cambia el diseño general
    de la página (eso queda para una conversación de diseño aparte),
    solo agrega un widget más a la grilla existente, con el mismo
    patrón que los demás (una tarjeta que se arma con JS al cargar).
    """
    hoy_local = (datetime.now(timezone.utc) - timedelta(hours=3)).date()
    desde = hoy_local - timedelta(days=dias - 1)

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT fecha_venta, COALESCE(SUM(precio_venta * cantidad), 0)
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s
            GROUP BY fecha_venta
        """, (desde, hoy_local))
        por_fecha = {fila[0]: float(fila[1]) for fila in cursor.fetchall()}

    serie = []
    for i in range(dias):
        fecha = desde + timedelta(days=i)
        serie.append({"fecha": fecha.strftime("%d/%m"), "facturado": round(por_fecha.get(fecha, 0.0), 2)})

    total_periodo = sum(p["facturado"] for p in serie)
    return {
        "serie": serie, "total_formateado": formatear_moneda(total_periodo),
        "promedio_diario_formateado": formatear_moneda(total_periodo / dias if dias else 0),
    }


def obtener_quiebre_stock(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        return analisis_stock.obtener_variantes_en_riesgo(cursor)


def obtener_resumen_diario(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        return resumen_semanal.obtener_datos_resumen_diario(cursor)


def obtener_reclamos_resumen(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        # Solo tipo='claim' es un reclamo real (el único que MeLi puede
        # contar contra la reputación) — 'return' es una devolución simple
        # (botón de arrepentimiento) y 'cancelacion' ni siquiera es eso.
        # Antes solo se excluía 'cancelacion', así que toda devolución
        # sin resolver se mostraba acá como si fuera un reclamo grave.
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(monto_retenido),0) FROM incidencias_posventa
            WHERE estado NOT IN ('closed','resolved') AND tipo = 'claim'
        """)
        cantidad, monto = cursor.fetchone()
    return {"cantidad": cantidad, "monto_formateado": formatear_moneda(monto)}


def obtener_costos_resumen(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT titulo, precio, precio_costo, recibis_estimado FROM productos_padre
            WHERE estado = 'active' AND precio > 0 AND recibis_estimado IS NOT NULL
        """)
        filas = cursor.fetchall()

    margenes = []
    for titulo, precio, costo, recibis in filas:
        precio, costo, recibis = float(precio), float(costo or 0), float(recibis)
        comision = precio - recibis
        margen_pct = round(((precio - comision - costo) / precio) * 100, 1)
        margenes.append({"titulo": titulo, "margen_pct": margen_pct})

    if not margenes:
        return {"margen_promedio": None, "peor": None}

    margen_promedio = round(sum(m["margen_pct"] for m in margenes) / len(margenes), 1)
    peor = min(margenes, key=lambda m: m["margen_pct"])
    return {"margen_promedio": margen_promedio, "peor": peor}

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


def obtener_ventas_hoy(usuario_id):
    arg_now = datetime.now(timezone.utc) - timedelta(hours=3)
    hoy_local = arg_now.strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id) as conexion:
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


def obtener_ticker(usuario_id):
    # Mismo criterio que obtener_ventas_hoy: "hoy" es el día en Argentina
    # (UTC-3), no el del reloj del sistema donde corra el proceso — si
    # alguna vez esto corre en un servidor en UTC en vez de en la PC del
    # usuario, datetime.now() a secas daría el día equivocado justo en las
    # horas cercanas a la medianoche.
    arg_now = datetime.now(timezone.utc) - timedelta(hours=3)
    hoy = arg_now.strftime("%Y-%m-%d")
    manana = (arg_now + timedelta(days=1)).strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id) as conexion:
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

        cursor.execute("SELECT COUNT(*) FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved')")
        incidencias_activas = cursor.fetchone()[0] or 0

        salud = salud_cuenta.calcular_score_salud(cursor)

    return {
        "ventas_hoy": ord_hoy, "facturado_hoy": formatear_moneda(fact_hoy),
        "liberacion_manana": formatear_moneda(liberacion_manana), "bridge_activo": False,
        "incidencias_activas": incidencias_activas, "salud_score": salud["score"],
        "salud_etiqueta": salud["etiqueta"], "salud_detalle": salud["detalle"],
        "ventas_hoy_detalle": ventas_hoy_detalle
    }


def obtener_quiebre_stock(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        return analisis_stock.obtener_variantes_en_riesgo(cursor)


def obtener_resumen_diario(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        return resumen_semanal.obtener_datos_resumen_diario(cursor)


def obtener_reclamos_resumen(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(monto_retenido),0) FROM incidencias_posventa
            WHERE estado NOT IN ('closed','resolved') AND tipo != 'cancelacion'
        """)
        cantidad, monto = cursor.fetchone()
    return {"cantidad": cantidad, "monto_formateado": formatear_moneda(monto)}


def obtener_costos_resumen(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
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

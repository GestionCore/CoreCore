"""Resumen de período estructurado — portado de Santi Mens (solo la parte de datos, sin el texto libre de IA que no se usa en el widget del dashboard)."""
from datetime import datetime, timedelta
import analisis_stock
from utils import formatear_moneda


def generar_resumen_periodo(cursor, dias=7):
    hoy = datetime.now()
    hoy_str = hoy.strftime("%Y-%m-%d")
    ayer_str = (hoy - timedelta(days=1)).strftime("%Y-%m-%d")

    if dias == 1:
        hace_dias = hoy_str
        hace_2x_dias = ayer_str
        hace_dias_mas_1 = ayer_str
    else:
        hace_dias = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
        hace_2x_dias = (hoy - timedelta(days=dias * 2)).strftime("%Y-%m-%d")
        hace_dias_mas_1 = (hoy - timedelta(days=dias + 1)).strftime("%Y-%m-%d")

    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0), COUNT(DISTINCT id_orden), COALESCE(SUM(cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_dias, hoy_str))
    fact_periodo, ordenes_periodo, unidades_periodo = cursor.fetchone()
    fact_periodo = float(fact_periodo or 0.0)

    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_2x_dias, hace_dias_mas_1))
    fact_periodo_anterior = float(cursor.fetchone()[0] or 0.0)

    variacion_pct = None
    if fact_periodo_anterior > 0:
        variacion_pct = round(((fact_periodo - fact_periodo_anterior) / fact_periodo_anterior) * 100, 1)

    cursor.execute("""
        SELECT titulo, SUM(cantidad) as total FROM ventas WHERE fecha_venta BETWEEN %s AND %s
        GROUP BY id_meli, titulo ORDER BY total DESC LIMIT 1
    """, (hace_dias, hoy_str))
    fila_top = cursor.fetchone()
    modelo_top = fila_top[0] if fila_top else None

    cursor.execute("SELECT COUNT(*) FROM alertas_curva_talles")
    curva_rota_abiertas = cursor.fetchone()[0] or 0

    en_riesgo_stock = len(analisis_stock.obtener_variantes_en_riesgo(cursor))

    cursor.execute("SELECT COUNT(*) FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved')")
    incidencias_abiertas = cursor.fetchone()[0] or 0

    return {
        "facturado_semana": fact_periodo, "ordenes_semana": ordenes_periodo, "unidades_semana": unidades_periodo,
        "variacion_pct": variacion_pct, "modelo_top": modelo_top,
        "curva_rota_abiertas": curva_rota_abiertas, "en_riesgo_stock": en_riesgo_stock,
        "incidencias_abiertas": incidencias_abiertas,
    }


def obtener_datos_resumen_diario(cursor):
    datos = generar_resumen_periodo(cursor, dias=1)
    return {
        "facturado_formateado": formatear_moneda(datos["facturado_semana"]),
        "ordenes": datos["ordenes_semana"], "unidades": datos["unidades_semana"], "modelo_top": datos["modelo_top"],
        "variacion_pct": datos["variacion_pct"], "curva_rota_abiertas": datos["curva_rota_abiertas"],
        "en_riesgo_stock": datos["en_riesgo_stock"], "incidencias_abiertas": datos["incidencias_abiertas"],
    }

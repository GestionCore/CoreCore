"""Resumen del día estructurado — portado de Santi Mens (solo la parte de datos, sin el texto libre de IA que no se usa en el widget del dashboard)."""
from datetime import datetime, timedelta
import analisis_stock
from utils import formatear_moneda, SQL_RECLAMO_AFECTA, ARGENTINA, sql_momento_argentina


def generar_resumen_dia(cursor, ahora=None):
    """
    Lo de hoy contra AYER A ESTA MISMA HORA. Antes se comparaba lo facturado hoy hasta ahora con el día de ayer ENTERO: a las 6 de la mañana la tarjeta «Ventas hoy» decía
    «▼ 86 % vs. ayer» en rojo sin que hubiera pasado nada (el mismo criterio que ya usa el hero: `dashboard.ganancia_de_ayer_hasta_la_hora`). `ahora` es la hora argentina (para probar).
    """
    ahora = ahora or datetime.now(ARGENTINA)
    hoy_str = ahora.strftime("%Y-%m-%d")
    corte_ayer = (ahora - timedelta(days=1)).replace(tzinfo=None)                  # ayer a esta hora
    inicio_ayer = corte_ayer.replace(hour=0, minute=0, second=0, microsecond=0)

    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0), COUNT(DISTINCT id_orden), COALESCE(SUM(cantidad),0) FROM ventas WHERE fecha_venta = %s", (hoy_str,))
    fact_hoy, ordenes_hoy, unidades_hoy = cursor.fetchone()
    fact_hoy = float(fact_hoy or 0.0)

    cursor.execute(f"SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE {sql_momento_argentina()} BETWEEN %s AND %s", (inicio_ayer, corte_ayer))
    fact_ayer_hasta_ahora = float(cursor.fetchone()[0] or 0.0)

    variacion_pct = None
    if fact_ayer_hasta_ahora > 0:
        variacion_pct = round(((fact_hoy - fact_ayer_hasta_ahora) / fact_ayer_hasta_ahora) * 100, 1)

    cursor.execute("""
        SELECT titulo, SUM(cantidad) as total FROM ventas WHERE fecha_venta = %s
        GROUP BY id_meli, titulo ORDER BY total DESC LIMIT 1
    """, (hoy_str,))
    fila_top = cursor.fetchone()
    modelo_top = fila_top[0] if fila_top else None

    variantes_clave_agotadas = len(analisis_stock.evaluar_cobertura_variantes(cursor))

    en_riesgo_stock = len(analisis_stock.obtener_variantes_en_riesgo(cursor))

    # Mismo criterio que dashboard.obtener_reclamos_resumen: esto alimenta
    # el HUD "Reclamos abiertos" (ver global.js), así que solo debe contar
    # tipo='claim' — una devolución simple (tipo='return') no es un
    # reclamo y no debería sumar acá, aunque siga sin resolver.
    cursor.execute(f"SELECT COUNT(*) FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved') AND tipo = 'claim' AND {SQL_RECLAMO_AFECTA}")
    incidencias_abiertas = cursor.fetchone()[0] or 0

    return {
        "facturado_dia": fact_hoy, "ordenes_dia": ordenes_hoy, "unidades_dia": unidades_hoy,
        "variacion_pct": variacion_pct, "modelo_top": modelo_top,
        "variantes_clave_agotadas": variantes_clave_agotadas, "en_riesgo_stock": en_riesgo_stock,
        "incidencias_abiertas": incidencias_abiertas,
    }


def obtener_datos_resumen_diario(cursor, ahora=None):
    datos = generar_resumen_dia(cursor, ahora)
    return {
        "facturado_formateado": formatear_moneda(datos["facturado_dia"]),
        "ordenes": datos["ordenes_dia"], "unidades": datos["unidades_dia"], "modelo_top": datos["modelo_top"],
        "variacion_pct": datos["variacion_pct"], "variantes_clave_agotadas": datos["variantes_clave_agotadas"],
        "en_riesgo_stock": datos["en_riesgo_stock"], "incidencias_abiertas": datos["incidencias_abiertas"],
    }

"""Score de Salud de Cuenta — portado de Santi Mens."""
from datetime import timedelta
import analisis_stock
from utils import SQL_RECLAMO_AFECTA, hoy_argentina, plural


def calcular_score_salud(cursor):
    score = 100
    detalle = []

    # Solo los reclamos reales ('claim') restan: una devolución o una cancelación no afectan la reputación
    cursor.execute(f"SELECT COUNT(*) FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved') AND tipo = 'claim' AND {SQL_RECLAMO_AFECTA}")
    reclamos_activos = cursor.fetchone()[0] or 0
    if reclamos_activos > 0:
        resta = min(reclamos_activos * 15, 45)
        score -= resta
        detalle.append(f"-{resta} por {plural(reclamos_activos, 'reclamo activo', 'reclamos activos')}")

    cursor.execute("""
        SELECT COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0) as stock_variante
        FROM productos_variantes v
        JOIN productos_padre p ON p.id = v.id_padre
        WHERE p.estado = 'active'
    """)
    stocks_variantes = [row[0] for row in cursor.fetchall()]
    variantes_sin_stock = sum(1 for s in stocks_variantes if s == 0)
    variantes_stock_bajo = sum(1 for s in stocks_variantes if 1 <= s <= 2)

    if variantes_sin_stock > 0:
        resta = min(variantes_sin_stock * 4, 20)
        score -= resta
        detalle.append(f"-{resta} por {plural(variantes_sin_stock, 'variante')} sin stock dentro de publicaciones activas")
    if variantes_stock_bajo > 0:
        resta = min(variantes_stock_bajo * 2, 10)
        score -= resta
        detalle.append(f"-{resta} por {plural(variantes_stock_bajo, 'variante')} con stock muy bajo (1-2 u.)")

    try:
        variantes_clave = len(analisis_stock.evaluar_cobertura_variantes(cursor))
        if variantes_clave > 0:
            resta = min(variantes_clave * 10, 20)
            score -= resta
            detalle.append(f"-{resta} por {plural(variantes_clave, 'variante clave', 'variantes clave')} sin stock (aportan más del 30 % de las ventas de su modelo)")
    except Exception as e:
        print(f"[Salud] ⚠️ No se pudo evaluar la cobertura de variantes clave: {e}")

    hoy = hoy_argentina().strftime("%Y-%m-%d")
    hace_7 = (hoy_argentina() - timedelta(days=7)).strftime("%Y-%m-%d")
    hace_14 = (hoy_argentina() - timedelta(days=14)).strftime("%Y-%m-%d")

    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_7, hoy))
    ventas_ultima_semana = float(cursor.fetchone()[0] or 0.0)
    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_14, hace_7))
    ventas_semana_anterior = float(cursor.fetchone()[0] or 0.0)

    if ventas_semana_anterior > 0:
        variacion_pct = ((ventas_ultima_semana - ventas_semana_anterior) / ventas_semana_anterior) * 100
        if variacion_pct <= -20:
            score -= 15
            detalle.append(f"-15 por caída de facturación de {round(variacion_pct)}% vs. la semana anterior")

    cursor.execute("""
        SELECT COUNT(*) FROM preguntas_pendientes
        WHERE estado = 'pendiente' AND creado_en < (now() - interval '1 day')
    """)
    preguntas_viejas = cursor.fetchone()[0] or 0
    if preguntas_viejas > 0:
        score -= 10
        detalle.append(f"-10 por {plural(preguntas_viejas, 'pregunta')} sin responder hace más de 24 h")

    score = max(0, min(100, score))

    if score >= 85: etiqueta = "Muy bien"
    elif score >= 65: etiqueta = "Bien"
    elif score >= 45: etiqueta = "Atención"
    else: etiqueta = "Crítico"

    return {"score": score, "etiqueta": etiqueta, "detalle": detalle}

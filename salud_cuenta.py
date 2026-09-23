"""Score de Salud de Cuenta — portado de Santi Mens."""
from datetime import datetime, timedelta
import analisis_stock


def calcular_score_salud(cursor):
    score = 100
    detalle = []

    cursor.execute("SELECT COUNT(*) FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved')")
    reclamos_activos = cursor.fetchone()[0] or 0
    if reclamos_activos > 0:
        resta = min(reclamos_activos * 15, 45)
        score -= resta
        detalle.append(f"-{resta} por {reclamos_activos} reclamo(s)/devolución(es) activa(s)")

    cursor.execute("""
        SELECT COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0) as stock_talle
        FROM productos_variantes v
        JOIN productos_padre p ON p.id = v.id_padre
        WHERE p.estado = 'active'
    """)
    stocks_talles = [row[0] for row in cursor.fetchall()]
    talles_sin_stock = sum(1 for s in stocks_talles if s == 0)
    talles_stock_bajo = sum(1 for s in stocks_talles if 1 <= s <= 2)

    if talles_sin_stock > 0:
        resta = min(talles_sin_stock * 4, 20)
        score -= resta
        detalle.append(f"-{resta} por {talles_sin_stock} talle(s) sin stock dentro de publicaciones activas")
    if talles_stock_bajo > 0:
        resta = min(talles_stock_bajo * 2, 10)
        score -= resta
        detalle.append(f"-{resta} por {talles_stock_bajo} talle(s) con stock muy bajo (1-2 u.)")

    try:
        modelos_con_curva_rota = len(analisis_stock.evaluar_curva_talles(cursor))
        if modelos_con_curva_rota > 0:
            resta = min(modelos_con_curva_rota * 10, 20)
            score -= resta
            detalle.append(f"-{resta} por {modelos_con_curva_rota} modelo(s) con curva de talles rota")
    except Exception:
        pass

    hoy = datetime.now().strftime("%Y-%m-%d")
    hace_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    hace_14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

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
        detalle.append(f"-10 por {preguntas_viejas} pregunta(s) sin responder hace más de 24hs")

    score = max(0, min(100, score))

    if score >= 85: etiqueta = "Muy bien"
    elif score >= 65: etiqueta = "Bien"
    elif score >= 45: etiqueta = "Atención"
    else: etiqueta = "Crítico"

    return {"score": score, "etiqueta": etiqueta, "detalle": detalle}

"""
Historial de Precios — portado de Santi Mens. El original usaba la
función date(?, '+N days') de SQLite, que no existe en Postgres; en vez
de traducir a la sintaxis de intervalos de Postgres dentro del SQL,
calculamos las fechas límite en Python y las pasamos ya resueltas —
más simple y más fácil de leer que mezclar aritmética de fechas dentro
de la consulta.
"""
from datetime import datetime, timedelta


def obtener_historial_con_impacto(cursor, dias_ventana=7, limite=40):
    cursor.execute("""
        SELECT hp.id_meli, hp.precio_anterior, hp.precio_nuevo, hp.fecha_cambio, p.titulo
        FROM historial_precios hp
        LEFT JOIN productos_padre p ON p.id_meli = hp.id_meli
        ORDER BY hp.fecha_cambio DESC LIMIT %s
    """, (limite,))
    cambios = cursor.fetchall()

    resultado = []
    for id_meli, precio_anterior, precio_nuevo, fecha_cambio, titulo in cambios:
        fecha_cambio_dt = fecha_cambio if hasattr(fecha_cambio, "date") else datetime.strptime(str(fecha_cambio)[:10], "%Y-%m-%d")
        fecha_cambio_date = fecha_cambio_dt.strftime("%Y-%m-%d")

        desde_antes = (fecha_cambio_dt - timedelta(days=dias_ventana)).strftime("%Y-%m-%d")
        hasta_antes = (fecha_cambio_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT COALESCE(SUM(cantidad), 0) FROM ventas
            WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s
        """, (id_meli, desde_antes, hasta_antes))
        unidades_antes = cursor.fetchone()[0] or 0

        hasta_despues = (fecha_cambio_dt + timedelta(days=dias_ventana)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT COALESCE(SUM(cantidad), 0) FROM ventas
            WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s
        """, (id_meli, fecha_cambio_date, hasta_despues))
        unidades_despues = cursor.fetchone()[0] or 0

        variacion_pct = None
        if unidades_antes > 0:
            variacion_pct = round(((unidades_despues - unidades_antes) / unidades_antes) * 100, 1)

        resultado.append({
            "id_meli": id_meli, "titulo": titulo or id_meli,
            "precio_anterior": precio_anterior, "precio_nuevo": precio_nuevo,
            "direccion": "subió" if precio_nuevo > precio_anterior else "bajó",
            "fecha_cambio": fecha_cambio_date,
            "unidades_antes": unidades_antes, "unidades_despues": unidades_despues,
            "variacion_pct": variacion_pct,
            "datos_incompletos": (unidades_antes == 0)
        })

    return resultado

"""
Historial de Precios — portado de Santi Mens. El original usaba la
función date(?, '+N days') de SQLite, que no existe en Postgres; en vez
de traducir a la sintaxis de intervalos de Postgres dentro del SQL,
calculamos las fechas límite en Python y las pasamos ya resueltas —
más simple y más fácil de leer que mezclar aritmética de fechas dentro
de la consulta.

Las unidades vendidas antes y después de cada cambio salen de UNA sola consulta de ventas (por publicación y día) para todos los
cambios: antes eran dos consultas por cambio (hasta 80 viajes a la base para 40 cambios).
"""
from datetime import datetime, timedelta


def unidades_en_ventana(ventas_por_item, id_meli, desde, hasta):
    """Suma las unidades de `id_meli` entre `desde` y `hasta` (ambos incluidos, 'AAAA-MM-DD'). `ventas_por_item` = {id_meli: [(fecha 'AAAA-MM-DD', unidades)]}."""
    return sum(unidades for fecha, unidades in ventas_por_item.get(id_meli, ()) if desde <= fecha <= hasta)


def ventas_diarias(cursor, ids, desde, hasta):
    """{id_meli: [(fecha 'AAAA-MM-DD', unidades)]} de las publicaciones `ids` entre `desde` y `hasta`, en una sola consulta."""
    if not ids:
        return {}
    cursor.execute("""
        SELECT id_meli, fecha_venta, COALESCE(SUM(cantidad), 0) FROM ventas
        WHERE id_meli = ANY(%s) AND fecha_venta BETWEEN %s AND %s
        GROUP BY id_meli, fecha_venta
    """, (list(ids), desde, hasta))
    por_item = {}
    for id_meli, fecha, unidades in cursor.fetchall():
        por_item.setdefault(id_meli, []).append((str(fecha)[:10], int(unidades or 0)))
    return por_item


def obtener_historial_con_impacto(cursor, dias_ventana=7, limite=40):
    cursor.execute("""
        SELECT hp.id_meli, hp.precio_anterior, hp.precio_nuevo, hp.fecha_cambio, p.titulo, p.thumbnail
        FROM historial_precios hp
        LEFT JOIN productos_padre p ON p.id_meli = hp.id_meli
        ORDER BY hp.fecha_cambio DESC LIMIT %s
    """, (limite,))
    cambios = cursor.fetchall()

    ventanas = []
    for id_meli, precio_anterior, precio_nuevo, fecha_cambio, titulo, thumbnail in cambios:
        fecha_cambio_dt = fecha_cambio if hasattr(fecha_cambio, "date") else datetime.strptime(str(fecha_cambio)[:10], "%Y-%m-%d")
        ventanas.append({
            "fecha": fecha_cambio_dt.strftime("%Y-%m-%d"),
            "desde_antes": (fecha_cambio_dt - timedelta(days=dias_ventana)).strftime("%Y-%m-%d"),
            "hasta_antes": (fecha_cambio_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            "hasta_despues": (fecha_cambio_dt + timedelta(days=dias_ventana)).strftime("%Y-%m-%d"),
        })
    ventas = ventas_diarias(cursor, {c[0] for c in cambios}, min((v["desde_antes"] for v in ventanas), default=None), max((v["hasta_despues"] for v in ventanas), default=None)) if cambios else {}

    resultado = []
    for (id_meli, precio_anterior, precio_nuevo, fecha_cambio, titulo, thumbnail), v in zip(cambios, ventanas):
        unidades_antes = unidades_en_ventana(ventas, id_meli, v["desde_antes"], v["hasta_antes"])
        unidades_despues = unidades_en_ventana(ventas, id_meli, v["fecha"], v["hasta_despues"])

        variacion_pct = None
        if unidades_antes > 0:
            variacion_pct = round(((unidades_despues - unidades_antes) / unidades_antes) * 100, 1)

        resultado.append({
            "id_meli": id_meli, "titulo": titulo or id_meli, "thumbnail": thumbnail,
            "precio_anterior": precio_anterior, "precio_nuevo": precio_nuevo,
            "direccion": "subió" if precio_nuevo > precio_anterior else "bajó",
            "fecha_cambio": v["fecha"],
            "unidades_antes": unidades_antes, "unidades_despues": unidades_despues,
            "variacion_pct": variacion_pct,
            "datos_incompletos": (unidades_antes == 0)
        })

    return resultado

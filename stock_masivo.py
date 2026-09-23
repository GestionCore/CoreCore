"""Stock Masivo — portado de Santi Mens."""
import re
import db
from utils import limpiar_titulo_modelo

ORDEN_LETRAS = {"S": 1, "M": 2, "L": 3, "XL": 4, "XXL": 5, "XXXL": 6}
ORDEN_ESTADO = {"active": 0, "paused": 1, "closed": 2}


def obtener_modelos_agrupados(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT p.id_meli, p.titulo, p.estado, p.thumbnail,
                   COALESCE(SUM(v.stock_propio), 0) as propio,
                   COALESCE(SUM(v.stock_full), 0) as full
            FROM productos_padre p
            LEFT JOIN productos_variantes v ON v.id_padre = p.id
            GROUP BY p.id_meli, p.titulo, p.estado, p.thumbnail
            ORDER BY p.titulo
        """)
        todos = cursor.fetchall()

    modelos = {}
    for id_meli, titulo, estado, thumbnail, propio, full in todos:
        clave = limpiar_titulo_modelo(titulo)
        match_talle = re.search(r'\b(XXXL|XXL|XL|L|M|S|\d+)\b', titulo, re.IGNORECASE)
        talle = match_talle.group(0).upper() if match_talle else "Único"
        if clave not in modelos:
            modelos[clave] = {"titulo": clave, "thumbnail": thumbnail, "propio": 0, "full": 0, "variantes": []}
        m = modelos[clave]
        m["propio"] += propio
        m["full"] += full
        pausada_por_stock = (estado == 'paused' and propio == 0 and full == 0)
        m["variantes"].append({"id_meli": id_meli, "talle": talle, "estado": estado, "propio": propio, "full": full, "pausada_por_stock": pausada_por_stock})

    for m in modelos.values():
        m["variantes"].sort(key=lambda v: (ORDEN_ESTADO.get(v["estado"], 3), ORDEN_LETRAS.get(v["talle"], 100)))

    return sorted(
        modelos.values(),
        key=lambda m: (min(ORDEN_ESTADO.get(v["estado"], 3) for v in m["variantes"]) if m["variantes"] else 3, m["titulo"])
    )

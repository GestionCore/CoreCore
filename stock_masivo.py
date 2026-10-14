"""Stock Masivo — portado de Santi Mens."""
import re

import db
from utils import limpiar_titulo_modelo, normalizar_talle, rotulo_variante

ORDEN_LETRAS = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4, "XXL": 5, "XXXL": 6}
ORDEN_ESTADO = {"active": 0, "paused": 1, "closed": 2}


def orden_de_talle(talle):
    """
    Cómo ordenar las variantes de un modelo sin suponer el rubro: primero las letras de ropa en su orden (S, M, L, XL…), después lo que empieza con un número en orden
    numérico (38, 39, 128 GB, 4 L, 20 L) y al final el resto alfabéticamente. «Único» va último.
    """
    t = str(talle or "").strip().upper()
    if t in ORDEN_LETRAS:
        return (0, ORDEN_LETRAS[t], "")
    numero = re.match(r"\d+(?:[.,]\d+)?", t)
    if numero:
        return (1, float(numero.group().replace(",", ".")), t)
    return (3 if t in ("", "ÚNICO") else 2, 0, t)


def obtener_modelos_agrupados(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        # El talle sale del atributo de Mercado Libre guardado en la variante (no del título); una publicación con varios talles adentro no tiene uno solo
        cursor.execute("""
            SELECT p.id_meli, p.titulo, p.estado, p.thumbnail,
                   COALESCE(SUM(v.stock_propio), 0) as propio,
                   COALESCE(SUM(v.stock_full), 0) as full,
                   CASE WHEN COUNT(DISTINCT NULLIF(v.talle, 'Único')) = 1 THEN MAX(NULLIF(v.talle, 'Único')) END AS talle_real,
                   CASE WHEN COUNT(DISTINCT v.etiqueta) = 1 THEN MAX(v.etiqueta) END AS etiqueta
            FROM productos_padre p
            LEFT JOIN productos_variantes v ON v.id_padre = p.id
            GROUP BY p.id_meli, p.titulo, p.estado, p.thumbnail
            ORDER BY p.titulo
        """)
        todos = cursor.fetchall()

    modelos = {}
    for id_meli, titulo, estado, thumbnail, propio, full, talle_real, etiqueta in todos:
        clave = limpiar_titulo_modelo(titulo, talle_real)
        talle = normalizar_talle(talle_real)
        if clave not in modelos:
            modelos[clave] = {"titulo": clave, "thumbnail": thumbnail, "propio": 0, "full": 0, "variantes": []}
        m = modelos[clave]
        m["propio"] += propio
        m["full"] += full
        pausada_por_stock = (estado == 'paused' and propio == 0 and full == 0)
        m["variantes"].append({"id_meli": id_meli, "talle": talle, "variante": rotulo_variante(etiqueta, talle_real), "estado": estado, "propio": propio, "full": full, "pausada_por_stock": pausada_por_stock})

    for m in modelos.values():
        m["variantes"].sort(key=lambda v: (ORDEN_ESTADO.get(v["estado"], 3), orden_de_talle(v["talle"]), orden_de_talle(v["variante"])))

    return sorted(
        modelos.values(),
        key=lambda m: (min(ORDEN_ESTADO.get(v["estado"], 3) for v in m["variantes"]) if m["variantes"] else 3, m["titulo"])
    )

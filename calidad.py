"""
Calidad de las publicaciones: el puntaje que Mercado Libre le da a cada una (0 a 100) y qué mejorarle, cruzado con las visitas
y las ventas. Todo sale de productos_padre (lo completa enriquecimiento.py en segundo plano): esta pantalla nunca espera a la API.

Sirve a cualquier rubro: las acciones y sus textos las define Mercado Libre para cada publicación.
"""
from collections import Counter

from utils import extraer_talle, formatear_moneda, limpiar_titulo_modelo, nombre_tipo_publicacion

UMBRAL_BIEN = 90
UMBRAL_JUSTO = 70
MIN_VISITAS_PARA_TENDENCIA = 20   # con muy pocas visitas el porcentaje no dice nada


def _tono(score):
    if score is None:
        return "neutral"
    return "ok" if score >= UMBRAL_BIEN else ("warn" if score >= UMBRAL_JUSTO else "danger")


def obtener_datos(cursor, cuenta_id):
    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.thumbnail, p.permalink, p.calidad_score, p.calidad_nivel, p.calidad_acciones,
               p.visitas_14d, p.visitas_previas_14d, COALESCE(v.unidades, 0), p.listing_type_id, p.precio,
               (SELECT string_agg(DISTINCT x.talle, ',') FROM productos_variantes x WHERE x.id_padre = p.id)
        FROM productos_padre p
        LEFT JOIN (SELECT id_meli, SUM(cantidad) AS unidades FROM ventas
                   WHERE cuenta_id = %(c)s AND origen = 'meli' AND fecha_venta >= current_date - 13 GROUP BY id_meli) v ON v.id_meli = p.id_meli
        WHERE p.cuenta_id = %(c)s AND p.estado = 'active'
        ORDER BY p.titulo
    """, {"c": cuenta_id})
    items = []
    for id_meli, titulo, thumbnail, permalink, score, nivel, acciones, visitas, previas, unidades, tipo_id, precio, talles in cursor.fetchall():
        visitas = visitas or 0
        previas = previas or 0
        tendencia = round((visitas - previas) / previas * 100) if previas >= MIN_VISITAS_PARA_TENDENCIA else None
        acciones = acciones if isinstance(acciones, list) else []
        items.append({
            "id_meli": id_meli, "titulo": titulo or id_meli, "thumbnail": thumbnail, "permalink": permalink,
            "score": score, "nivel": nivel, "tono": _tono(score), "acciones": acciones,
            "visitas": visitas, "visitas_previas": previas, "tendencia": tendencia,
            "unidades": int(unidades), "conversion": round(unidades / visitas * 100, 2) if visitas > 0 else None,
            "sin_dato": score is None,
            "tipo": nombre_tipo_publicacion(tipo_id), "precio": float(precio) if precio is not None else None,
            # clave de "mismo modelo, mismo talle": una publicación con varios talles adentro no tiene un talle propio
            "_clave": (limpiar_titulo_modelo(titulo or id_meli), extraer_talle(titulo or id_meli, talles if talles and "," not in talles else None)),
        })

    # El mismo modelo y talle puede estar publicado varias veces (tipo Clásica y Premium, a precios distintos): se juntan en una fila con el detalle de cada una
    grupos = agrupar_publicaciones(items)

    con_dato = [i for i in items if i["score"] is not None]
    promedio = round(sum(i["score"] for i in con_dato) / len(con_dato)) if con_dato else None
    al_cien = sum(1 for i in con_dato if i["score"] >= 100)
    con_mejoras = [i for i in items if i["acciones"]]

    # Qué conviene arreglar primero: lo que más visitas recibe y peor puntaje tiene
    con_mejoras.sort(key=lambda i: (-(i["visitas"] * (100 - (i["score"] if i["score"] is not None else 100))), i["score"] if i["score"] is not None else 100))

    repetidas = Counter()
    ejemplos = {}
    for i in con_mejoras:
        for a in i["acciones"]:
            texto = a.get("texto") or a.get("variable") or "Mejora pendiente"
            repetidas[texto] += 1
            ejemplos.setdefault(texto, a.get("boton"))
    top_acciones = [{"texto": t, "cantidad": n, "boton": ejemplos.get(t)} for t, n in repetidas.most_common(5)]

    total_visitas = sum(i["visitas"] for i in items)
    total_previas = sum(i["visitas_previas"] for i in items)
    total_unidades = sum(i["unidades"] for i in items)
    visitas_max = max((i["visitas"] for i in items), default=0)
    for i in items:
        i["pct_visitas"] = max(round(i["visitas"] / visitas_max * 100), 3) if visitas_max and i["visitas"] else 0

    return {
        "items": items, "grupos": grupos, "promedio": promedio, "tono_promedio": _tono(promedio), "al_cien": al_cien, "con_dato": len(con_dato),
        "total_activas": len(items), "sin_revisar": sum(1 for i in items if i["sin_dato"]),
        "con_mejoras": con_mejoras, "top_acciones": top_acciones, "total_acciones": sum(len(i["acciones"]) for i in items),
        "total_visitas": total_visitas,
        "tendencia_visitas": round((total_visitas - total_previas) / total_previas * 100, 1) if total_previas >= MIN_VISITAS_PARA_TENDENCIA else None,
        "conversion": round(total_unidades / total_visitas * 100, 2) if total_visitas > 0 else None, "total_unidades": total_unidades,
        "mas_visitadas": sorted([i for i in items if i["visitas"]], key=lambda i: -i["visitas"])[:6],
        "perdiendo_visitas": sorted([i for i in items if i["tendencia"] is not None and i["tendencia"] <= -25], key=lambda i: i["tendencia"])[:6],
        "visitas_sin_ventas": sorted([i for i in items if i["visitas"] >= 100 and i["unidades"] == 0], key=lambda i: -i["visitas"])[:6],
    }


def etiqueta_publicacion(tipo, precio):
    """«Clásica · $65.990» — lo que distingue a dos publicaciones del mismo modelo y talle. Vacío si no hay ni tipo ni precio."""
    partes = [p for p in (tipo, f"${formatear_moneda(precio)}" if precio else None) if p]
    return " · ".join(partes)


def agrupar_publicaciones(items):
    """
    Junta las publicaciones del mismo modelo y talle. Devuelve una lista de grupos {titulo, thumbnail, talle, publicaciones, visitas, unidades, conversion,
    tendencia, score, tono}, con la conversión y la tendencia calculadas sobre la SUMA (no un promedio de porcentajes) y el puntaje de la peor publicación (es
    la que hay que mejorar). Cada publicación de un grupo con más de una recibe `etiqueta` («Clásica · $65.990»); las que están solas, no.
    """
    por_clave = {}
    for i in items:
        por_clave.setdefault(i["_clave"], []).append(i)
    grupos = []
    for clave, pubs in por_clave.items():
        pubs = sorted(pubs, key=lambda i: -i["visitas"])
        for i in pubs:
            i["hermanas"] = len(pubs)
            i["etiqueta"] = etiqueta_publicacion(i["tipo"], i["precio"]) if len(pubs) > 1 else ""
        visitas = sum(i["visitas"] for i in pubs)
        previas = sum(i["visitas_previas"] for i in pubs)
        unidades = sum(i["unidades"] for i in pubs)
        con_dato = [i["score"] for i in pubs if i["score"] is not None]
        score = min(con_dato) if con_dato else None
        grupos.append({
            "titulo": pubs[0]["titulo"], "thumbnail": next((i["thumbnail"] for i in pubs if i["thumbnail"]), None), "talle": clave[1], "publicaciones": pubs,
            "visitas": visitas, "visitas_previas": previas, "unidades": unidades,
            "conversion": round(unidades / visitas * 100, 2) if visitas > 0 else None,
            "tendencia": round((visitas - previas) / previas * 100) if previas >= MIN_VISITAS_PARA_TENDENCIA else None,
            "score": score, "tono": _tono(score),
        })
    return grupos

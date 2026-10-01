"""
Opiniones de compradores: qué calificación tienen tus productos, qué dicen quienes los compraron y qué conviene revisar.

Todo sale de productos_padre (lo completa enriquecimiento.refrescar_opiniones desde GET /reviews/item/{id}): esta pantalla nunca espera a
la API. Las publicaciones de un mismo modelo (todos sus talles o variantes) comparten opiniones y tienen el mismo family_id, así que
se agrupan por esa clave y cada opinión se cuenta UNA vez. Sirve a cualquier rubro: los atributos ("le quedó como esperaba", "la
calidad del material"...) los define Mercado Libre para cada categoría.
"""
from utils import limpiar_titulo_modelo

MIN_OPINIONES_PARA_JUZGAR = 5       # con menos, un promedio no dice nada
UMBRAL_PROMEDIO_BAJO = 4.3
UMBRAL_CRITICAS_PCT = 10            # % de opiniones de 1 y 2 estrellas a partir del cual se mira el producto
DIAS_VENTAS = 90


def _tono(promedio):
    if promedio is None:
        return "neutral"
    return "ok" if promedio >= 4.5 else ("warn" if promedio >= 4.0 else "danger")


def obtener_datos(cursor, cuenta_id):
    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.thumbnail, p.permalink, p.estado, p.family_id, p.opiniones_promedio, p.opiniones_total,
               p.opiniones_niveles, p.opiniones_atributos, p.opiniones_criticas, COALESCE(v.unidades, 0)
        FROM productos_padre p
        LEFT JOIN (SELECT id_meli, SUM(cantidad) AS unidades FROM ventas
                   WHERE cuenta_id = %(c)s AND origen = 'meli' AND fecha_venta >= current_date - %(d)s GROUP BY id_meli) v ON v.id_meli = p.id_meli
        WHERE p.cuenta_id = %(c)s AND p.estado IN ('active', 'paused') AND p.opiniones_en IS NOT NULL
    """, {"c": cuenta_id, "d": DIAS_VENTAS})

    familias = {}
    for id_meli, titulo, thumbnail, permalink, estado, family_id, promedio, total, niveles, atributos, criticas, unidades in cursor.fetchall():
        f = familias.setdefault(family_id or id_meli, {
            "titulo": limpiar_titulo_modelo(titulo) or id_meli, "thumbnail": thumbnail, "permalink": permalink, "activa": estado == "active",
            "promedio": float(promedio) if promedio is not None else None, "total": int(total or 0),
            "niveles": niveles or {}, "atributos": atributos or [], "criticas": criticas or [], "unidades": 0,
        })
        f["unidades"] += int(unidades)
        if int(total or 0) > f["total"]:     # algunas publicaciones (p. ej. pausadas) reportan 0: vale la que más opiniones trae
            f.update(promedio=float(promedio) if promedio is not None else None, total=int(total), niveles=niveles or {},
                     atributos=atributos or [], criticas=criticas or [])
        if estado == "active" and not f["activa"]:     # el representante es una publicación activa, si hay
            f.update(titulo=limpiar_titulo_modelo(titulo) or id_meli, thumbnail=thumbnail or f["thumbnail"], permalink=permalink, activa=True)

    con_opiniones = [f for f in familias.values() if f["total"] > 0]
    total_opiniones = sum(f["total"] for f in con_opiniones)
    niveles = {k: sum(int(f["niveles"].get(k) or 0) for f in con_opiniones) for k in "12345"}
    suma_estrellas = sum(int(k) * n for k, n in niveles.items())
    con_estrellas = sum(niveles.values())
    promedio = round(suma_estrellas / con_estrellas, 2) if con_estrellas else None

    def pct(n):
        return round(n / con_estrellas * 100, 1) if con_estrellas else 0

    for f in con_opiniones:
        n = sum(int(f["niveles"].get(k) or 0) for k in "12345") or f["total"]
        f["pct_criticas"] = round((int(f["niveles"].get("1") or 0) + int(f["niveles"].get("2") or 0)) / n * 100, 1) if n else 0
        f["tono"] = _tono(f["promedio"])
        f["distribucion"] = [{"estrellas": e, "cantidad": int(f["niveles"].get(str(e)) or 0),
                              "pct": round(int(f["niveles"].get(str(e)) or 0) / n * 100) if n else 0} for e in (5, 4, 3, 2, 1)]
        f["revisar"] = f["total"] >= MIN_OPINIONES_PARA_JUZGAR and ((f["promedio"] or 5) < UMBRAL_PROMEDIO_BAJO or f["pct_criticas"] >= UMBRAL_CRITICAS_PCT)

    productos = sorted(con_opiniones, key=lambda f: (-f["total"], f["titulo"]))
    revisar = sorted([f for f in con_opiniones if f["revisar"]], key=lambda f: (-f["unidades"], f["promedio"] or 5))

    # Lo que dicen los compradores que no quedaron conformes: las críticas más recientes de todos los productos
    criticas = sorted(
        [{**c, "producto": f["titulo"], "permalink": f["permalink"]} for f in con_opiniones for c in f["criticas"] if c.get("texto") or c.get("titulo")],
        key=lambda c: c.get("fecha") or "", reverse=True)[:10]

    return {
        "productos": productos, "revisar": revisar, "criticas": criticas, "total_opiniones": total_opiniones,
        "promedio": promedio, "tono": _tono(promedio), "niveles": niveles, "total_productos": len(familias),
        "pct_cinco": pct(niveles["5"]), "pct_buenas": pct(niveles["4"] + niveles["5"]), "pct_malas": pct(niveles["1"] + niveles["2"]),
        "sin_opiniones": len(familias) - len(con_opiniones), "ya_revisadas": len(familias) > 0,
    }

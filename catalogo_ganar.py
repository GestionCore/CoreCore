"""
Publicaciones de catálogo: quién tiene el puesto principal de la ficha y a qué precio se lo gana.

Mercado Libre muestra una sola oferta como principal en cada ficha de catálogo (la que se "gana" la compra). enriquecimiento.py
guarda, por publicación, el estado de la competencia (GET /items/{id}/price_to_win) y el precio al que se pasa al primero. Acá se cruza
con lo que le deja plata al vendedor (precios.py): bajar el precio para ganar solo conviene si después de la comisión, el envío y el
costo de fabricación sigue quedando ganancia.

Solo hay filas para cuentas con publicaciones de catálogo; para el resto devuelve None y la pantalla no muestra nada.
"""
import precios

ESTADOS = {
    "winning": ("ok", "Tenés el puesto principal"),
    "sharing_first_place": ("ok", "Compartís el primer lugar"),
    "competing": ("warn", "Otro vendedor tiene el puesto principal"),
    "listed": ("neutral", "Publicada en la ficha, sin competir por el puesto principal"),
}


def condiciones_del_ganador(detalle):
    """
    Las condiciones («boosts») que Mercado Libre informa para sostener el precio ganador: [{"id", "estado", "descripcion"}]. Una publicación puede ganar a $X con
    envío gratis y a $Y sin él, por eso el precio solo no alcanza. Lista vacía si no hay detalle guardado.
    """
    boosts = (detalle or {}).get("boosts") if isinstance(detalle, dict) else None
    return [{"id": b.get("id"), "estado": b.get("status"), "descripcion": b.get("description")} for b in (boosts or []) if isinstance(b, dict)]


def obtener(cursor, cuenta_id):
    cursor.execute("""
        SELECT id_meli, titulo, thumbnail, permalink, precio, catalogo_estado, catalogo_precio_para_ganar, catalogo_detalle
        FROM productos_padre
        WHERE cuenta_id = %s AND estado = 'active' AND catalog_product_id IS NOT NULL AND catalogo_estado IS NOT NULL
        ORDER BY titulo
    """, (cuenta_id,))
    filas = cursor.fetchall()
    if not filas:
        return None

    calculo = {i["id_meli"]: i for i in precios.obtener_datos(cursor, cuenta_id)["items"]}
    items = []
    for id_meli, titulo, thumbnail, permalink, precio, estado, para_ganar, detalle in filas:
        precio = float(precio or 0)
        para_ganar = float(para_ganar) if para_ganar is not None else None
        tono, texto = ESTADOS.get(estado, ("neutral", "Sin información de competencia todavía"))
        item = {"id_meli": id_meli, "titulo": titulo or id_meli, "thumbnail": thumbnail, "permalink": permalink, "precio": precio,
                "estado": estado, "tono": tono, "texto": texto, "para_ganar": None, "diferencia": None, "diferencia_pct": None,
                "neto_para_ganar": None, "conviene": None, "condiciones": condiciones_del_ganador(detalle)}
        if estado == "competing" and para_ganar and 0 < para_ganar < precio:
            item["para_ganar"] = para_ganar
            item["diferencia"] = round(precio - para_ganar, 2)
            item["diferencia_pct"] = round((precio - para_ganar) / precio * 100, 1)
            c = calculo.get(id_meli)
            if c:
                neto = para_ganar * (1 - c["comision_pct"] / 100) - c["envio"] - c["costo"]
                item["neto_para_ganar"] = round(neto, 2)
                item["conviene"] = neto > 0
        items.append(item)

    # Primero lo accionable: donde bajar el precio te da el puesto Y te deja ganancia; después donde habría que perder plata
    orden = {True: 0, None: 1, False: 2}
    items.sort(key=lambda i: (0 if i["estado"] == "competing" else 1, orden[i["conviene"]], i["titulo"]))
    return {
        "items": items,
        "ganando": sum(1 for i in items if i["estado"] in ("winning", "sharing_first_place")),
        "perdiendo": sum(1 for i in items if i["estado"] == "competing"),
        "conviene_bajar": sum(1 for i in items if i["conviene"]),
    }

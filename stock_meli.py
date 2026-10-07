"""
Cambios de stock en Mercado Libre (el depósito propio de una publicación). Lo usan Stock masivo y las ventas fuera de MeLi.

Lo que hay que saber:
  · El stock que ve CoreLux se vuelve a leer de Mercado Libre cada 4 minutos: un descuento hecho solo acá se pisa y la publicación sigue
    ofreciendo una unidad que ya no hay (sobreventa). Para que un descuento dure, hay que hacerlo en Mercado Libre.
  · Una publicación sin variaciones se guarda acá con la variante «<id>_unica» (id interno nuestro): a Mercado Libre se le manda
    `available_quantity` a nivel de la publicación. Con UNA variación real se manda esa variación. Con varias, no se toca (se revisa a mano).
  · Lo que está en FULL o convive con FULL (inventory_id) lo maneja Mercado Libre: no se escribe.
"""
import meli_errores
import meli_http

URL_ITEM = "https://api.mercadolibre.com/items/{}"
SUFIJO_SIN_VARIACIONES = "_unica"


def payload_para_stock(variantes, cantidad):
    """
    Cuerpo del PUT para dejar el stock en `cantidad`. `variantes` son los ids de variante guardados de esa publicación.
    Devuelve None cuando no se puede decidir sola (varias variaciones).
    """
    variantes = [str(v) for v in (variantes or [])]
    if not variantes or (len(variantes) == 1 and variantes[0].endswith(SUFIJO_SIN_VARIACIONES)):
        return {"available_quantity": int(cantidad)}
    if len(variantes) == 1:
        id_variacion = int(variantes[0]) if variantes[0].isdigit() else variantes[0]
        return {"variations": [{"id": id_variacion, "available_quantity": int(cantidad)}]}
    return None


def _cantidad_actual(item, id_variante):
    """Stock que Mercado Libre tiene HOY para esa variante (la variación, o la publicación si no tiene)."""
    if str(id_variante).endswith(SUFIJO_SIN_VARIACIONES) or not item.get("variations"):
        return int(item.get("available_quantity") or 0)
    for v in item["variations"]:
        if str(v.get("id")) == str(id_variante):
            return int(v.get("available_quantity") or 0)
    return None


def ajustar_en_meli(access_token, id_meli, id_variante, delta, obtener=None, escribir=None):
    """
    Suma `delta` (negativo = descontar) al stock que Mercado Libre tiene AHORA, nunca por debajo de cero. Se parte de lo que MeLi dice y no de lo
    que CoreLux tenía guardado, que puede tener minutos de atraso (una venta reciente se perdería).
    Devuelve (ok, mensaje, stock_nuevo). Nunca lanza.
    """
    obtener = obtener or meli_http.get
    escribir = escribir or meli_http.put
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        r = obtener(URL_ITEM.format(id_meli) + "?attributes=available_quantity,variations", headers=headers, timeout=10)
        if r.status_code != 200:
            return False, "No pudimos consultar el stock actual en Mercado Libre.", None
        actual = _cantidad_actual(r.json(), id_variante)
        if actual is None:
            return False, "Esa variación ya no existe en Mercado Libre.", None
        nuevo = max(actual + int(delta), 0)
        payload = payload_para_stock([id_variante], nuevo)
        w = escribir(URL_ITEM.format(id_meli), headers=headers, json=payload, timeout=10)
        if w.status_code not in (200, 201):
            return False, meli_errores.explicar_respuesta(w), None
        return True, "", nuevo
    except Exception as e:                      # red caída, respuesta rara: se informa, no se corta el flujo
        print(f"[StockMeli] No se pudo ajustar {id_meli}: {type(e).__name__}: {e}")
        return False, "No pudimos conectar con Mercado Libre.", None

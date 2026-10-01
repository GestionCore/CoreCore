"""
Mensajes de compradores sin leer (mensajería postventa de Mercado Libre).

GET /messages/unread?role=seller&tag=post_sale devuelve cuántos mensajes esperan respuesta y en qué órdenes. Acá solo se AVISA y se
lleva a cada conversación en Mercado Libre: responder se hace allá, que es donde Mercado Libre aplica sus reglas (largo máximo,
moderación, y las órdenes de FULL vienen bloqueadas porque las atiende Mercado Libre, no el vendedor).

Una cuenta sin mensajes devuelve total 0 y la pantalla no muestra nada.
"""
import re
import meli_http

_RE_ID = re.compile(r"/(?:orders|packs)/(\d+)")
URL_VENTA = "https://www.mercadolibre.com.ar/ventas/{}/detalle"


def sin_leer(access_token):
    """{"total": n, "conversaciones": [{id, cantidad, link}]} o None si Mercado Libre no respondió (no se sabe: no se muestra nada)."""
    try:
        resp = meli_http.get("https://api.mercadolibre.com/messages/unread", params={"role": "seller", "tag": "post_sale"},
                             headers={"Authorization": f"Bearer {access_token}"}, timeout=8)
    except Exception as e:
        print(f"[Mensajes] ⚠️ No se pudo consultar los mensajes sin leer: {e}")
        return None
    if resp.status_code != 200:
        return None
    datos = resp.json() or {}
    conversaciones = []
    for r in datos.get("results") or []:
        m = _RE_ID.search(str(r.get("resource") or ""))
        if m:
            conversaciones.append({"id": m.group(1), "cantidad": int(r.get("count") or 1), "link": URL_VENTA.format(m.group(1))})
    return {"total": int(datos.get("total") or 0), "conversaciones": conversaciones[:20]}

"""
Envío gratis según lo que informa Mercado Libre: nunca un piso supuesto (el umbral cambia con el tiempo y con la cuenta).

Fuentes, todas verificadas contra respuestas reales:
  · GET /users/{id}/shipping_preferences → `mandatory_settings.price_limit` (el piso desde el cual el envío gratis es obligatorio; 0 o ausente = MeLi no
    informa un piso) y `free_configurations` (lo que el propio vendedor ofrece gratis: `condition.type == "all"` = todo).
  · Cada publicación trae en `shipping` si es gratis (`free_shipping`) y si lo es por obligación (`tags` con `mandatory_free_shipping`).
  · GET /users/{id}/shipping_options/free calcula el costo para el vendedor, pero SIEMPRE rechaza (400) si no se le manda `item_id` o `dimensions`.
"""
import re

import meli_http

DIMENSIONES_VALIDAS = re.compile(r"^\d{1,3}x\d{1,3}x\d{1,3},\d{1,6}$")      # "alto x ancho x largo (cm), peso (g)": 10x20x30,500


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def interpretar_preferencias(prefs):
    """
    {"umbral_obligatorio": float | None, "vendedor_ofrece_gratis_siempre": bool}. umbral_obligatorio es None cuando MeLi no informa un piso:
    no se sabe, no equivale a «no hay envío gratis obligatorio».
    """
    prefs = prefs or {}
    limite = _numero((prefs.get("mandatory_settings") or {}).get("price_limit"))
    siempre = any(
        (c.get("condition") or {}).get("type") == "all" and (c.get("rule") or {}).get("default") is True
        for c in (prefs.get("free_configurations") or []) if isinstance(c, dict)
    )
    return {"umbral_obligatorio": limite if limite and limite > 0 else None, "vendedor_ofrece_gratis_siempre": siempre}


def es_obligatorio(precio, interpretacion):
    """True / False si MeLi informa un piso; None si no lo informa (no se puede afirmar nada)."""
    umbral = (interpretacion or {}).get("umbral_obligatorio")
    if umbral is None:
        return None
    return float(precio) >= umbral


def de_publicacion(shipping):
    """Lo que dice una publicación (el objeto `shipping` de GET /items/{id}) sobre su envío gratis."""
    shipping = shipping or {}
    return {"gratis": bool(shipping.get("free_shipping")), "obligatorio": "mandatory_free_shipping" in (shipping.get("tags") or [])}


def consultar(headers, user_id):
    """Interpretación de las preferencias de envío del vendedor, o None si Mercado Libre no respondió."""
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/users/{user_id}/shipping_preferences", headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        return interpretar_preferencias(resp.json())
    except Exception as e:
        print(f"[EnvioGratis] ⚠️ No se pudieron leer las preferencias de envío: {e}")
        return None


def costo_para_vendedor(headers, user_id, precio, item_id=None, dimensiones=None, listing_type_id="gold_special"):
    """
    (costo | None, obligatorio_gratis | None, motivo | None). Sin `item_id` ni `dimensiones` Mercado Libre no calcula el envío (da 400): se devuelve el motivo
    en vez de un cero que haría parecer la ganancia más alta de lo que es.
    """
    if not item_id and not (dimensiones and DIMENSIONES_VALIDAS.match(dimensiones)):
        return None, None, "Falta el peso y las medidas del paquete (o la publicación): Mercado Libre no calcula el envío sin eso."
    params = {"item_price": precio, "listing_type_id": listing_type_id, "mode": "me2", "condition": "new", "logistic_type": "drop_off"}
    if item_id:
        params["item_id"] = item_id
    else:
        params["dimensions"] = dimensiones
        params["verbose"] = "true"
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/users/{user_id}/shipping_options/free", headers=headers, params=params, timeout=10)
    except Exception as e:
        return None, None, f"No se pudo consultar el envío: {e}"
    if resp.status_code != 200:
        return None, None, f"Mercado Libre no calculó el envío ({resp.status_code})."
    datos = resp.json()
    costo = ((datos.get("coverage") or {}).get("all_country") or {}).get("list_cost")
    if costo is None:
        costo = datos.get("list_cost")
    return costo, "mandatory_free_shipping" in (datos.get("tags") or []) or None, None

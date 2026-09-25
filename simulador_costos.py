import meli_http
from datetime import datetime, timedelta

def simular_bajar_precio_vs_pausar(precio_actual, costo_fabricacion, reduccion_pct, unidades_vendidas_30d, headers, site_id="MLA", listing_type_id="gold_special"):
    """
    Compara dos caminos concretos para una publicación con pocas ventas:
    A) Bajar el precio X% — con la matemática real de cuántas unidades de
       más necesitarías vender solo para no perder plata (no inventamos
       si la demanda va a subir con el precio más bajo, eso lo sabés vos
       mejor que cualquier cálculo).
    B) Pausar la publicación — muestra la ganancia que te está dejando
       HOY con las ventas reales del período, para que decidas si ese
       resultado justifica seguir invirtiendo atención/stock ahí.
    """
    resultado_actual = simular_costos(precio_actual, costo_fabricacion, headers, site_id, listing_type_id)
    if not resultado_actual:
        return None

    nuevo_precio = round(precio_actual * (1 - reduccion_pct / 100), 2)
    resultado_nuevo = simular_costos(nuevo_precio, costo_fabricacion, headers, site_id, listing_type_id)
    if not resultado_nuevo:
        return None

    ganancia_actual_total = resultado_actual["ganancia_neta"] * unidades_vendidas_30d

    unidades_necesarias = None
    unidades_extra_pct = None
    if resultado_nuevo["ganancia_neta"] > 0:
        unidades_necesarias = ganancia_actual_total / resultado_nuevo["ganancia_neta"]
        if unidades_vendidas_30d > 0:
            unidades_extra_pct = round(((unidades_necesarias - unidades_vendidas_30d) / unidades_vendidas_30d) * 100, 1)

    caida_margen_pct = None
    if resultado_actual["ganancia_neta"] > 0:
        caida_margen_pct = round((1 - resultado_nuevo["ganancia_neta"] / resultado_actual["ganancia_neta"]) * 100, 1)

    return {
        "precio_actual": round(precio_actual, 2),
        "margen_actual_unidad": resultado_actual["ganancia_neta"],
        "nuevo_precio": nuevo_precio,
        "margen_nuevo_unidad": resultado_nuevo["ganancia_neta"],
        "caida_margen_pct": caida_margen_pct,
        "unidades_actuales_30d": unidades_vendidas_30d,
        "ganancia_actual_total_30d": round(ganancia_actual_total, 2),
        "unidades_necesarias_30d": round(unidades_necesarias, 1) if unidades_necesarias is not None else None,
        "unidades_extra_pct": unidades_extra_pct,
    }


def simular_costos(precio, costo_fabricacion, headers, site_id="MLA", listing_type_id="gold_special"):
    comision = None
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/sites/{site_id}/listing_prices", headers=headers, params={"price": precio}, timeout=8)
        if resp.status_code == 200:
            opciones = resp.json()
            match = next((o for o in opciones if o.get("listing_type_id") == listing_type_id), None)
            if match:
                comision = match.get("sale_fee_amount")
    except Exception as e:
        print(f"[Simulador] ⚠️ Error consultando comisión: {e}")

    if comision is None:
        return None

    ganancia_neta = round(precio - comision - costo_fabricacion, 2)
    margen_pct = round((ganancia_neta / precio) * 100, 1) if precio > 0 else 0.0
    return {"comision": round(comision, 2), "ganancia_neta": ganancia_neta, "margen_pct": margen_pct}


def calcular_precio_objetivo(ganancia_deseada, costo_fabricacion, costo_envio_estimado, headers, site_id="MLA", listing_type_id="gold_special"):
    """
    Calcula qué precio necesitás cobrar para que, después de la comisión REAL
    de MeLi para ese precio, te quede la ganancia neta pedida en mano.
    Como la comisión no siempre es un % puro (hay cargos fijos en rangos bajos
    de precio), se resuelve consultando la comisión real y ajustando por
    aproximaciones sucesivas, en vez de una fórmula algebraica fija.
    """
    precio_estimado = ganancia_deseada + costo_fabricacion + costo_envio_estimado
    if precio_estimado <= 0:
        return None

    comision = 0.0
    for _ in range(6):
        try:
            resp = meli_http.get(
                f"https://api.mercadolibre.com/sites/{site_id}/listing_prices",
                headers=headers, params={"price": round(precio_estimado, 2)}, timeout=8
            )
            if resp.status_code != 200:
                return None
            opciones = resp.json()
            match = next((o for o in opciones if o.get("listing_type_id") == listing_type_id), None)
            if not match or match.get("sale_fee_amount") is None:
                return None
            comision = match["sale_fee_amount"]
        except Exception as e:
            print(f"[Simulador Inverso] ⚠️ Error consultando comisión: {e}")
            return None

        nuevo_precio = ganancia_deseada + costo_fabricacion + costo_envio_estimado + comision
        if abs(nuevo_precio - precio_estimado) < 1:
            precio_estimado = nuevo_precio
            break
        precio_estimado = nuevo_precio

    return {
        "precio_sugerido": round(precio_estimado, 2),
        "comision_estimada": round(comision, 2),
        "ganancia_neta_resultante": round(precio_estimado - comision - costo_fabricacion - costo_envio_estimado, 2)
    }


NOMBRES_LISTING_TYPE = {
    "free": "Gratuita", "bronze": "Bronce", "silver": "Plata",
    "gold": "Clásica", "gold_premium": "Premium", "gold_pro": "Premium", "gold_special": "Premium",
}

def comparar_listing_types(precio, costo_fabricacion, headers, site_id="MLA", id_meli=None):
    """
    Trae TODAS las opciones de tipo de publicación que existen para ese
    precio y calcula qué ganancia neta daría cada una. Si se pasa id_meli,
    marca cuál es el tipo actual de esa publicación (un solo GET puntual).
    """
    tipo_actual = None
    if id_meli:
        try:
            resp_item = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, timeout=8)
            if resp_item.status_code == 200:
                tipo_actual = resp_item.json().get("listing_type_id")
        except Exception:
            pass

    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/sites/{site_id}/listing_prices", headers=headers, params={"price": precio}, timeout=8)
        if resp.status_code != 200:
            return None
        opciones = resp.json()
    except Exception as e:
        print(f"[Comparador Listing] ⚠️ Error: {e}")
        return None

    comparacion = []
    for o in opciones:
        tipo_id = o.get("listing_type_id")
        comision = o.get("sale_fee_amount")
        if comision is None:
            continue
        ganancia_neta = round(precio - comision - costo_fabricacion, 2)
        margen_pct = round((ganancia_neta / precio) * 100, 1) if precio > 0 else 0.0
        comparacion.append({
            "listing_type_id": tipo_id, "nombre": NOMBRES_LISTING_TYPE.get(tipo_id, tipo_id),
            "comision": round(comision, 2), "ganancia_neta": ganancia_neta, "margen_pct": margen_pct,
            "es_actual": (tipo_id == tipo_actual)
        })

    comparacion.sort(key=lambda x: -x["ganancia_neta"])
    return comparacion

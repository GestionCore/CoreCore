"""
Calculadora de Costos real de Mercado Libre — usa las mismas APIs
oficiales que ya usamos en el simulador de Costos, ampliadas para
mostrar el desglose completo (comisión base vs. costo de cuotas) y el
costo de envío real para un precio dado, sin inventar ningún porcentaje
de blogs de terceros.
"""
import requests


def obtener_categorias_del_catalogo(headers, cursor, limite=30):
    """
    Devuelve las categorías reales de tus publicaciones activas (id +
    nombre), para que elijas una en vez de escribir un category_id a
    mano. Solo consulta hasta `limite` items para no demorar.
    """
    cursor.execute("SELECT id_meli FROM productos_padre WHERE estado = 'active' LIMIT ?", (limite,))
    ids = [r[0] for r in cursor.fetchall()]
    if not ids:
        return []

    categorias_vistas = {}
    for id_meli in ids:
        try:
            resp = requests.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, timeout=6)
            if resp.status_code != 200:
                continue
            data = resp.json()
            cat_id = data.get("category_id")
            if cat_id and cat_id not in categorias_vistas:
                resp_cat = requests.get(f"https://api.mercadolibre.com/categories/{cat_id}", timeout=6)
                nombre = resp_cat.json().get("name", cat_id) if resp_cat.status_code == 200 else cat_id
                categorias_vistas[cat_id] = nombre
        except Exception:
            continue

    return [{"id": k, "nombre": v} for k, v in categorias_vistas.items()]


def calcular_desglose_real(access_token, precio, category_id, listing_type_id, ofrece_cuotas, site_id="MLA"):
    """
    Trae el desglose REAL de una venta a este precio: comisión base,
    costo de cuotas (si aplica), costo fijo, y costo de envío — todo
    consultado directo a la API oficial, no calculado con porcentajes
    fijos que podrían estar desactualizados.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Comisión + desglose de cuotas, vía listing_prices
    params_precio = {"price": precio, "category_id": category_id, "listing_type_id": listing_type_id}
    if ofrece_cuotas:
        params_precio["tags"] = "ahora-3"  # tag genérico de campaña de cuotas del BNA (la más común en MLA)

    try:
        resp = requests.get(f"https://api.mercadolibre.com/sites/{site_id}/listing_prices", headers=headers, params=params_precio, timeout=10)
        if resp.status_code != 200:
            return {"error": f"No se pudo consultar la comisión real: {resp.status_code} - {resp.text[:200]}"}
        opciones = resp.json()
        if not isinstance(opciones, list) or not opciones:
            return {"error": "MeLi no devolvió opciones de comisión para estos parámetros."}

        opcion = next((o for o in opciones if o.get("listing_type_id") == listing_type_id), opciones[0])
        detalle_comision = opcion.get("sale_fee_details", {}) or {}
        comision_total = opcion.get("sale_fee_amount", 0) or 0
        pct_comision_base = detalle_comision.get("meli_percentage_fee")
        pct_cuotas = detalle_comision.get("financing_add_on_fee")
        cargo_fijo = detalle_comision.get("fixed_fee", 0) or 0

    except Exception as e:
        return {"error": f"Error de conexión consultando comisión: {e}"}

    # 2. Costo de envío real / elegibilidad de envío gratis, vía shipping_options
    costo_envio = None
    envio_obligatorio_gratis = None
    try:
        user_id_resp = requests.get("https://api.mercadolibre.com/users/me", headers=headers, timeout=8)
        user_id = user_id_resp.json().get("id") if user_id_resp.status_code == 200 else None
        if user_id:
            resp_envio = requests.get(
                f"https://api.mercadolibre.com/users/{user_id}/shipping_options/free",
                headers=headers,
                params={"item_price": precio, "listing_type_id": listing_type_id, "mode": "me2", "condition": "new", "logistic_type": "drop_off"},
                timeout=10
            )
            if resp_envio.status_code == 200:
                data_envio = resp_envio.json()
                opciones_envio = data_envio.get("coverage", {}).get("all_country", {}).get("list_cost")
                costo_envio = opciones_envio if opciones_envio is not None else data_envio.get("list_cost")
                envio_obligatorio_gratis = "mandatory_free_shipping" in (data_envio.get("tags") or [])
    except Exception as e:
        print(f"[Calculadora] ⚠️ No se pudo consultar el costo de envío: {e}")

    ganancia_antes_de_costo_producto = precio - comision_total - (costo_envio or 0)

    return {
        "precio": precio,
        "comision_total": round(comision_total, 2),
        "pct_comision_base": pct_comision_base,
        "pct_cuotas": pct_cuotas if ofrece_cuotas else None,
        "cargo_fijo": cargo_fijo,
        "costo_envio": round(costo_envio, 2) if costo_envio is not None else None,
        "envio_obligatorio_gratis": envio_obligatorio_gratis,
        "recibis": round(ganancia_antes_de_costo_producto, 2),
    }

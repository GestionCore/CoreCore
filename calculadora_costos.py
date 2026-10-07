"""
Calculadora de Costos real de Mercado Libre — usa las mismas APIs
oficiales que ya usamos en el simulador de Costos, ampliadas para
mostrar el desglose completo (comisión base vs. costo de cuotas) y el
costo de envío real para un precio dado, sin inventar ningún porcentaje
de blogs de terceros.
"""
import time
from concurrent.futures import ThreadPoolExecutor
import envio_gratis
import meli_http

# Nombre de categoría por category_id — es un dato global de MeLi (no
# depende de la cuenta), así que a diferencia de las otras cachés del
# proyecto no necesita ir indexado por cuenta_id. Las categorías casi
# no cambian de nombre, TTL largo como en logistica.py.
_cache_nombre_categoria = {}
_cache_camino_categoria = {}
TTL_SEGUNDOS = 6 * 3600


def caminos_de_categorias(cat_ids, headers=None):
    """
    {category_id: "Ropa y Accesorios › Ropa Deportiva › Medias"} para varias categorías a la vez.
    MeLi devuelve categorías con el MISMO nombre en rubros distintos (hay 5 "Medias": ropa interior,
    deportiva, bebés, hockey…); sin el camino completo no hay forma de saber cuál elegir.
    """
    def _camino(cat_id):
        cacheado = _cache_camino_categoria.get(cat_id)
        if cacheado and (time.time() - cacheado[1]) < TTL_SEGUNDOS:
            return cat_id, cacheado[0]
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/categories/{cat_id}", headers=headers or {})
            if resp.status_code != 200:
                return cat_id, None
            data = resp.json()
            camino = " › ".join(p["name"] for p in (data.get("path_from_root") or [])) or data.get("name")
        except Exception:
            return cat_id, None
        _cache_camino_categoria[cat_id] = (camino, time.time())
        return cat_id, camino

    unicos = list(dict.fromkeys(cat_ids))
    if not unicos:
        return {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(_camino, unicos))


def obtener_categorias_del_catalogo(headers, cursor, limite=30):
    """
    Devuelve las categorías reales de tus publicaciones activas (id +
    nombre), para que elijas una en vez de escribir un category_id a
    mano. Solo consulta hasta `limite` items para no demorar.
    """
    cursor.execute("SELECT id_meli FROM productos_padre WHERE estado = 'active' LIMIT %s", (limite,))
    ids = [r[0] for r in cursor.fetchall()]
    if not ids:
        return []

    def _category_id_de(id_meli):
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers)
            if resp.status_code != 200:
                return None
            return resp.json().get("category_id")
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        category_ids = list(pool.map(_category_id_de, ids))

    cat_ids_unicos = []
    for cat_id in category_ids:
        if cat_id and cat_id not in cat_ids_unicos:
            cat_ids_unicos.append(cat_id)

    def _nombre_de(cat_id):
        cacheado = _cache_nombre_categoria.get(cat_id)
        if cacheado and (time.time() - cacheado[1]) < TTL_SEGUNDOS:
            return cat_id, cacheado[0]
        try:
            resp_cat = meli_http.get(f"https://api.mercadolibre.com/categories/{cat_id}")
            nombre = resp_cat.json().get("name", cat_id) if resp_cat.status_code == 200 else cat_id
        except Exception:
            nombre = cat_id
        _cache_nombre_categoria[cat_id] = (nombre, time.time())
        return cat_id, nombre

    with ThreadPoolExecutor(max_workers=8) as pool:
        pares = list(pool.map(_nombre_de, cat_ids_unicos))

    return [{"id": cat_id, "nombre": nombre} for cat_id, nombre in pares]


def calcular_desglose_real(access_token, precio, category_id, listing_type_id, ofrece_cuotas, site_id="MLA", item_id=None, dimensiones=None):
    """
    Trae el desglose REAL de una venta a este precio: comisión base,
    costo de cuotas (si aplica), costo fijo, y costo de envío — todo
    consultado directo a la API oficial, no calculado con porcentajes
    fijos que podrían estar desactualizados.

    El costo de envío necesita saber qué paquete es: `item_id` (una publicación propia) o `dimensiones` ("alto x ancho x largo en cm, peso en
    gramos", p. ej. "10x20x30,500"). Sin ninguno de los dos `costo_envio` queda en None y `envio_motivo` explica por qué.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Comisión + desglose de cuotas, vía listing_prices
    params_precio = {"price": precio, "category_id": category_id, "listing_type_id": listing_type_id}
    if ofrece_cuotas:
        params_precio["tags"] = "ahora-3"  # tag genérico de campaña de cuotas del BNA (la más común en MLA)

    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/sites/{site_id}/listing_prices", headers=headers, params=params_precio)
        if resp.status_code != 200:
            return {"error": f"No se pudo consultar la comisión real: {resp.status_code} - {resp.text[:200]}"}
        opciones = resp.json()
        # Con listing_type_id en la consulta MeLi devuelve UN objeto (no una
        # lista de opciones, como cuando no se lo pasa) — sin este
        # normalizado el cálculo siempre caía en el error de abajo.
        if isinstance(opciones, dict):
            opciones = [opciones]
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

    # 2. Envío: el piso del envío gratis sale de las preferencias del vendedor (nunca un número supuesto) y el costo de /shipping_options/free,
    #    que Mercado Libre rechaza (400) si no se le manda la publicación (item_id) o el peso y las medidas.
    costo_envio = None
    envio_obligatorio_gratis = None
    envio_gratis_desde = None
    envio_motivo = None
    try:
        user_id_resp = meli_http.get("https://api.mercadolibre.com/users/me", headers=headers)
        user_id = user_id_resp.json().get("id") if user_id_resp.status_code == 200 else None
        if user_id:
            preferencias = envio_gratis.consultar(headers, user_id)
            if preferencias:
                envio_gratis_desde = preferencias["umbral_obligatorio"]
                envio_obligatorio_gratis = envio_gratis.es_obligatorio(precio, preferencias)
            costo_envio, obligatorio_del_calculo, envio_motivo = envio_gratis.costo_para_vendedor(headers, user_id, precio, item_id, dimensiones, listing_type_id)
            if obligatorio_del_calculo:
                envio_obligatorio_gratis = True
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
        "envio_gratis_desde": envio_gratis_desde,
        "envio_motivo": envio_motivo,
        "recibis": round(ganancia_antes_de_costo_producto, 2),
    }

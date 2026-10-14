"""
Calculadora de Costos real de Mercado Libre — usa las mismas APIs
oficiales que ya usamos en el simulador de Costos, ampliadas para
mostrar el desglose completo (comisión base vs. costo de cuotas) y el
costo de envío real para un precio dado, sin inventar ningún porcentaje
de blogs de terceros.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import envio_gratis
import flex
import meli_http
from utils import formatear_moneda, hoy_argentina

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


# ── Unit Economics: lo que de verdad te deja UNA venta, con devoluciones, embalaje y publicidad ───────────────────────────────────────────────
BASE_LOTE = 100               # se piensa en un lote de 100 ventas: «14 devoluciones cada 100» se entiende sin hacer cuentas
VENTANA_REALES_DIAS = 90      # los datos reales de un producto salen de sus ventas de los últimos 90 días
MIN_UNIDADES_REALES = 3       # con menos ventas el dato es orientativo


def _num(valor, minimo=0.0):
    """Un número válido y no negativo (los campos vacíos, el texto y NaN/infinito valen 0)."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return max(v, minimo)


def simular_merma(precio, comision, costo_fabricacion=0, costo_envio=0, costo_ads=0, costo_embalaje=0, tasa_devolucion=0, costo_envio_devolucion=0):
    """
    Lo que cuesta y lo que deja UNA venta concretada, pensando en un lote de BASE_LOTE (100) ventas. Si `tasa_devolucion` es 14, 14 de las 100 vuelven y se concretan 86.
    Lo que se paga POR CADA UNA de las 100 aunque vuelva (publicidad, embalaje y el envío de ida) más el envío de vuelta de las devueltas es plata hundida: se reparte
    entre las 86 que sí se concretaron.
      · comisión y costo de fabricación: solo de las ventas concretadas (en una devolución Mercado Libre reintegra la comisión y el producto vuelve a tu stock);
      · hundido = 100 × (publicidad + embalaje + envío de ida) + devoluciones × envío de devolución;
      · costo de una venta = comisión + fabricación + hundido ÷ ventas concretadas; ganancia = precio − ese costo.
    Con la tasa en 0 da lo mismo que sumar los costos de una venta sola. {"error": ...} si no hay precio o si TODAS vuelven (no se concreta ninguna).
    """
    precio, comision = _num(precio), _num(comision)
    costo_fabricacion, costo_envio, costo_ads, costo_embalaje, costo_envio_devolucion = (_num(x) for x in (costo_fabricacion, costo_envio, costo_ads, costo_embalaje, costo_envio_devolucion))
    tasa = _num(tasa_devolucion)
    if precio <= 0:
        return {"error": "Falta el precio de venta."}
    if tasa >= 100:
        return {"error": "Con el 100 % de devoluciones no se concreta ninguna venta: no hay ganancia por unidad."}
    concretadas = BASE_LOTE * (1 - tasa / 100)
    devoluciones = BASE_LOTE - concretadas
    hundido_total = BASE_LOTE * (costo_ads + costo_embalaje + costo_envio) + devoluciones * costo_envio_devolucion
    por_venta = {
        "comision": comision, "fabricacion": costo_fabricacion,
        "envio": BASE_LOTE * costo_envio / concretadas, "ads": BASE_LOTE * costo_ads / concretadas, "embalaje": BASE_LOTE * costo_embalaje / concretadas,
        "devoluciones": devoluciones * costo_envio_devolucion / concretadas,
    }
    costo_total = sum(por_venta.values())
    ganancia = precio - costo_total
    sin_devoluciones = precio - comision - costo_fabricacion - costo_envio - costo_ads - costo_embalaje
    return {
        "base": BASE_LOTE, "devoluciones": round(devoluciones, 2), "concretadas": round(concretadas, 2), "tasa_devolucion": tasa,
        "hundido_total": round(hundido_total, 2), "hundido_por_venta": round(hundido_total / concretadas, 2),
        "por_venta": {k: round(v, 2) for k, v in por_venta.items()},
        "costo_total_por_venta": round(costo_total, 2), "ganancia_por_venta": round(ganancia, 2), "margen_pct": round(ganancia / precio * 100, 1),
        "ganancia_sin_devoluciones": round(sin_devoluciones, 2), "costo_de_las_devoluciones": round(sin_devoluciones - ganancia, 2),
        "frase": _frase_merma(devoluciones, concretadas, costo_total, ganancia),
    }


def _cantidad(n):
    """86 → «86»; 87,5 → «87,5»."""
    n = round(n, 1)
    return str(int(n)) if float(n).is_integer() else str(n).replace(".", ",")


def _frase_merma(devoluciones, concretadas, costo_total, ganancia):
    """La cuenta dicha en una frase (solo si hay devoluciones: sin ellas no hay nada que absorber)."""
    if devoluciones <= 0:
        return None
    final = f"te deja ${formatear_moneda(ganancia)} limpios" if ganancia >= 0 else f"te hace perder ${formatear_moneda(abs(ganancia))}"
    return (f"Tuviste que pagar {BASE_LOTE} envíos/ads para concretar {_cantidad(concretadas)} ventas. "
            f"Absorbiendo esa pérdida, vender 1 sola unidad te cuesta realmente ${formatear_moneda(costo_total)} y {final}.")


def escala_flex(umbrales):
    """
    La escala de entrega Flex que cargó el vendedor (los precios de sus umbrales, ver flex.py): {"minimo", "maximo", "promedio"}. El promedio es el punto medio del rango
    (si paga entre $4.000 y $10.000 se asume $7.000). None si no cargó ningún precio. Son precios brutos: no se les descuenta el reintegro de Mercado Libre.
    """
    precios = []
    for u in umbrales or []:
        try:
            p = float(u.get("precio"))
        except (TypeError, ValueError):
            continue
        if p > 0:
            precios.append(p)
    if not precios:
        return None
    return {"minimo": min(precios), "maximo": max(precios), "promedio": round((min(precios) + max(precios)) / 2, 2)}


def datos_de_producto(cursor, cuenta_id, id_meli, hoy=None):
    """
    Lo que CoreLux ya sabe de una publicación para completar la calculadora sin que la persona escriba nada: precio, categoría, tipo de publicación y costo de fabricación
    cargados, la comisión, el envío y las retenciones REALES de sus ventas de los últimos 90 días, y la escala Flex del vendedor. None si la publicación no existe.
    `reales` es None si no vendió en esos 90 días (nada se estima con otros productos: el envío de dos productos no se parece).
    """
    cursor.execute("SELECT id_meli, titulo, thumbnail, precio, precio_costo, category_id, listing_type_id FROM productos_padre WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, id_meli))
    fila = cursor.fetchone()
    if not fila:
        return None
    id_meli, titulo, thumbnail, precio, costo, category_id, listing_type_id = fila
    desde = (hoy or hoy_argentina()) - timedelta(days=VENTANA_REALES_DIAS)
    cursor.execute("""
        SELECT COALESCE(SUM(cantidad), 0), COALESCE(SUM(precio_venta * cantidad), 0), COALESCE(SUM(COALESCE(cargo_venta, 0)), 0), COALESCE(SUM(COALESCE(costo_envio, 0)), 0),
               COALESCE(SUM(retenciones), 0), COALESCE(SUM(precio_venta * cantidad) FILTER (WHERE retenciones IS NOT NULL), 0)
        FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND id_meli = %s AND fecha_venta >= %s
    """, (cuenta_id, id_meli, desde))
    unidades, ingreso, cargos, envios, retenciones, ingreso_con_retenciones = (float(x or 0) for x in cursor.fetchone())
    reales = None
    if unidades > 0 and ingreso > 0:
        reales = {"dias": VENTANA_REALES_DIAS, "unidades": int(unidades), "comision_pct": round(cargos / ingreso * 100, 1), "comision_unitaria": round(cargos / unidades, 2),
                  "envio_unitario": round(envios / unidades, 2), "pocas_ventas": unidades < MIN_UNIDADES_REALES,
                  "retenciones_pct": round(retenciones / ingreso_con_retenciones * 100, 2) if ingreso_con_retenciones > 0 else None}
    return {"id_meli": id_meli, "titulo": titulo or id_meli, "thumbnail": thumbnail, "precio": float(precio) if precio else None,
            "costo_fabricacion": float(costo) if costo else None, "category_id": category_id, "listing_type_id": listing_type_id,
            "reales": reales, "flex": escala_flex(flex.obtener_config(cursor, cuenta_id)["umbrales"])}

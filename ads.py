"""
Publicidad (Product Ads) — portado de Santi Mens.

Cambio real respecto al original, no cosmético: `obtener_advertiser_info`
cacheaba por `site_id` solo (ej: "MLA") — como CASI TODAS las cuentas
argentinas van a pasar "MLA", esa caché iba a devolver el advertiser_id
de la PRIMERA cuenta que la llenara a CUALQUIER otra cuenta que
consultara después. En single-tenant esto nunca se notaba porque solo
había una cuenta. Acá la clave de caché ahora incluye cuenta_id.

También dejé afuera dos funciones que quedaron redundantes en el
original: `_obtener_costos_ads_por_item_OBSOLETO` (ya estaba marcada
como tal) y `obtener_gasto_ads_por_dia`, que usaba un patrón de endpoint
con aggregation_type=DAILY nunca confirmado del todo — `obtener_serie_diaria_ads`
hace lo mismo con el patrón que sí confirmamos que funciona, y ya la
reemplazaba en la práctica.
"""
import time
import meli_http
import concurrent.futures
from datetime import datetime, timedelta
from utils import hoy_argentina

_advertiser_cache = {}
_costos_cache = {}
TTL_COSTOS_SEGUNDOS = 300  # 5 minutos

METRICAS_CAMPANA = "clicks,prints,ctr,cost,cpc,acos,roas,cvr,units_quantity,direct_amount,indirect_amount,total_amount"


def obtener_ad_de_item(access_token, id_meli):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/advertising/product_ads/items/{id_meli}", headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {"campaign_id": data.get("campaign_id"), "status": data.get("status")}
    except Exception as e:
        print(f"[Ads] ⚠️ Error buscando anuncio de {id_meli}: {e}")
        return None


def pausar_ad_item(access_token, id_meli):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        resp = meli_http.put(
            f"https://api.mercadolibre.com/advertising/product_ads/items/{id_meli}",
            json={"status": "paused"}, headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"Error de conexión: {e}"


def obtener_advertiser_info(access_token, cuenta_id, site_id_esperado="MLA"):
    """
    cuenta_id es obligatorio a propósito — es lo que hace que la caché no
    se mezcle entre cuentas distintas (ver nota del módulo).
    """
    clave_cache = (cuenta_id, site_id_esperado)
    if clave_cache in _advertiser_cache:
        return _advertiser_cache[clave_cache]

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Api-Version": "1"}
    url = "https://api.mercadolibre.com/advertising/advertisers?product_id=PADS"

    try:
        resp = meli_http.get(url, headers=headers, timeout=10)
    except Exception as e:
        print(f"[Ads] ❌ Error de conexión consultando advertiser_id: {e}")
        return None, None

    if resp.status_code != 200:
        print(f"[Ads] ⚠️ Error consultando advertiser_id: {resp.status_code} - {resp.text[:300]}")
        return None, None

    anunciantes = resp.json().get("advertisers", [])
    match = next((a for a in anunciantes if a.get("site_id") == site_id_esperado), None)
    if not match:
        return None, None

    resultado = (match.get("advertiser_id"), match.get("site_id"))
    _advertiser_cache[clave_cache] = resultado
    return resultado


def obtener_advertiser_id(access_token, cuenta_id, site_id="MLA"):
    advertiser_id, _ = obtener_advertiser_info(access_token, cuenta_id, site_id)
    return advertiser_id


def obtener_campanas_con_metricas(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id="MLA"):
    headers = {"Authorization": f"Bearer {access_token}", "api-version": "2"}
    url = (
        f"https://api.mercadolibre.com/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search"
        f"?limit=50&offset=0&date_from={fecha_desde}&date_to={fecha_hasta}&metrics={METRICAS_CAMPANA}&metrics_summary=true"
    )
    try:
        resp = meli_http.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[Ads] ⚠️ Error trayendo campañas: {resp.status_code} - {resp.text[:300]}")
            return []
        data = resp.json()
        campanas = []
        for c in data.get("results", []):
            metricas = c.get("metrics", {}) or {}
            # El campo "budget" de una campaña real vino como un número
            # directo en la práctica (no como {"amount": N}, que era lo
            # que asumíamos sin haber podido confirmarlo contra la API
            # real todavía) — lo hacemos robusto a las dos formas.
            budget_raw = c.get("budget")
            presupuesto = budget_raw.get("amount") if isinstance(budget_raw, dict) else budget_raw
            campanas.append({
                "id": c.get("id"), "nombre": c.get("name", "Sin nombre"), "estado": c.get("status", "unknown"),
                "presupuesto": presupuesto,
                "clicks": metricas.get("clicks", 0), "prints": metricas.get("prints", 0),
                # CTR y CVR se calculan acá: el que manda MeLi viene en escalas distintas según la campaña (una con 8 clics
                # figuraba con 230%). Mismo criterio que el embudo de Publicidad: clics / impresiones y unidades / clics.
                "ctr": round((metricas.get("clicks") or 0) / metricas["prints"] * 100, 2) if metricas.get("prints") else 0,
                "costo": metricas.get("cost", 0) or 0,
                "cpc": metricas.get("cpc", 0) or 0, "roas": metricas.get("roas"), "acos": metricas.get("acos"),
                "cvr": round((metricas.get("units_quantity") or 0) / metricas["clicks"] * 100, 2) if metricas.get("clicks") else 0,
                "unidades": metricas.get("units_quantity", 0),
                "ventas_atribuidas": metricas.get("total_amount", 0) or 0,
                # direct = vendiste el ítem que anunciaste; indirect = el
                # comprador llegó por el anuncio pero terminó comprando
                # otro producto del catálogo. MeLi ya lo manda separado
                # en la métrica, antes se pedía pero se descartaba acá.
                "venta_directa": metricas.get("direct_amount", 0) or 0,
                "venta_indirecta": metricas.get("indirect_amount", 0) or 0,
            })
        return campanas
    except Exception as e:
        print(f"[Ads] ❌ Error de conexión trayendo campañas: {e}")
        return []


def obtener_serie_diaria_ads(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id="MLA"):
    d1 = datetime.strptime(fecha_desde, "%Y-%m-%d")
    d2 = datetime.strptime(fecha_hasta, "%Y-%m-%d")
    dias = [(d1 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d2 - d1).days + 1)]

    headers = {"Authorization": f"Bearer {access_token}", "api-version": "2"}

    def _consultar_dia(fecha):
        url = (
            f"https://api.mercadolibre.com/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search"
            f"?limit=50&offset=0&date_from={fecha}&date_to={fecha}&metrics=cost,total_amount,units_quantity"
        )
        try:
            resp = meli_http.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return fecha, 0.0, 0.0, 0
            data = resp.json()
            costo_dia = sum(float((c.get("metrics", {}) or {}).get("cost") or 0) for c in data.get("results", []))
            ventas_dia = sum(float((c.get("metrics", {}) or {}).get("total_amount") or 0) for c in data.get("results", []))
            unidades_dia = sum(int((c.get("metrics", {}) or {}).get("units_quantity") or 0) for c in data.get("results", []))
            return fecha, costo_dia, ventas_dia, unidades_dia
        except Exception:
            return fecha, 0.0, 0.0, 0

    por_dia = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for fecha, costo, ventas, unidades in executor.map(_consultar_dia, dias):
            por_dia[fecha] = {"costo": costo, "ventas": ventas, "unidades": unidades}
    return por_dia


DIAS_HISTORIA_ADS = 89      # la API de Product Ads solo da métricas de los últimos 90 días (más atrás responde 400)


def obtener_gasto_ads_total_periodo(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id="MLA"):
    """
    Gasto total de Product Ads del período, recorriendo todas las páginas de campañas. Si el período empieza antes de lo que la API
    guarda (90 días atrás) devuelve None sin consultar: un total parcial se vería como si fuera el gasto completo.
    """
    from datetime import date, timedelta
    try:
        if date.fromisoformat(str(fecha_desde)[:10]) < hoy_argentina() - timedelta(days=DIAS_HISTORIA_ADS):
            return None
    except ValueError:
        return None
    headers = {"Authorization": f"Bearer {access_token}", "api-version": "2"}
    total, offset = 0.0, 0
    try:
        while offset < 1000:
            url = (
                f"https://api.mercadolibre.com/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search"
                f"?limit=50&offset={offset}&date_from={fecha_desde}&date_to={fecha_hasta}&metrics=cost"
            )
            resp = meli_http.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"[Ads] ⚠️ Error consultando gasto total: {resp.status_code} - {resp.text[:300]}")
                return None
            resultados = resp.json().get("results", [])
            total += sum(float(c.get("metrics", {}).get("cost") or 0) for c in resultados)
            if len(resultados) < 50:
                break
            offset += 50
        return round(total, 2)
    except Exception as e:
        print(f"[Ads] ❌ Error de conexión trayendo gasto total: {e}")
        return None


_metricas_item_cache = {}
_anuncios_cache = {}
TTL_ANUNCIOS_SEGUNDOS = 300
ANUNCIOS_POR_PAGINA = 50
TOPE_PAGINAS_ANUNCIOS = 40          # 2.000 anuncios: mucho más que cualquier cuenta real


def obtener_anuncios_con_metricas(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id="MLA"):
    """
    {item_id: {costo, ventas, unidades, clicks, prints, titulo, thumbnail}} de TODOS los anuncios de Product Ads del anunciante en el período, con el listado
    paginado `/product_ads/ads/search` (50 por página). Antes se hacía una consulta por publicación: medido con datos reales en 2 cuentas, 4 llamadas en 0,9 s
    contra 192 en 5,5 s, con los mismos números (0 diferencias en 86 + 117 + 20 + 33 anuncios con datos, en períodos de 14 y 60 días).
    Devuelve None si no se pudo leer completo (una página falló o se cortó la conexión): quien llama vuelve a la consulta por publicación, porque un listado
    a medias se vería como «esas publicaciones no gastaron».
    """
    clave_cache = (advertiser_id, fecha_desde, fecha_hasta)
    cacheado = _anuncios_cache.get(clave_cache)
    if cacheado and (time.time() - cacheado["timestamp"]) < TTL_ANUNCIOS_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}", "api-version": "2"}
    anuncios, offset = {}, 0
    try:
        for _ in range(TOPE_PAGINAS_ANUNCIOS):
            url = (
                f"https://api.mercadolibre.com/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/ads/search"
                f"?limit={ANUNCIOS_POR_PAGINA}&offset={offset}&date_from={fecha_desde}&date_to={fecha_hasta}&metrics=cost,total_amount,units_quantity,clicks,prints"
            )
            resp = meli_http.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"[Ads] ⚠️ El listado de anuncios respondió {resp.status_code}: se consulta publicación por publicación.")
                return None
            datos = resp.json() or {}
            resultados = datos.get("results") or []
            for a in resultados:
                item_id = a.get("item_id")
                if not item_id:
                    continue
                m = a.get("metrics") or {}
                anuncios[item_id] = {
                    "costo": float(m.get("cost") or 0.0), "ventas": float(m.get("total_amount") or 0.0), "unidades": int(m.get("units_quantity") or 0),
                    "clicks": int(m.get("clicks") or 0), "prints": int(m.get("prints") or 0),
                    "titulo": a.get("title"), "thumbnail": (a.get("thumbnail") or "").replace("http://", "https://") or None,
                }
            offset += ANUNCIOS_POR_PAGINA
            total = (datos.get("paging") or {}).get("total")
            if len(resultados) < ANUNCIOS_POR_PAGINA or (total is not None and offset >= int(total)):
                break
        else:
            print("[Ads] ⚠️ El listado de anuncios superó el tope de páginas: se consulta publicación por publicación.")
            return None
    except Exception as e:
        print(f"[Ads] ⚠️ No se pudo leer el listado de anuncios ({e}): se consulta publicación por publicación.")
        return None

    if len(_anuncios_cache) > 50:
        _anuncios_cache.clear()
    _anuncios_cache[clave_cache] = {"data": anuncios, "timestamp": time.time()}
    return anuncios


def obtener_metricas_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_relevantes, site_id="MLA"):
    """
    {id_meli: {costo, ventas, unidades, clicks, prints, titulo, thumbnail}} de cada publicación que gastó o tuvo impresiones
    en Product Ads en el período (las que no están en Ads se omiten). Es lo que permite ver el retorno POR PUBLICACIÓN y
    detectar las que gastan sin vender. Sale del listado de anuncios (4 llamadas); si ese falla, una consulta por publicación, en paralelo.
    """
    clave_cache = (advertiser_id, fecha_desde, fecha_hasta, tuple(sorted(ids_relevantes)))
    cacheado = _metricas_item_cache.get(clave_cache)
    if cacheado and (time.time() - cacheado["timestamp"]) < TTL_COSTOS_SEGUNDOS:
        return cacheado["data"]

    listado = obtener_anuncios_con_metricas(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id)
    if listado is not None:
        relevantes = set(ids_relevantes)
        resultado = {i: a for i, a in listado.items() if i in relevantes and (a["costo"] > 0 or a["prints"] > 0)}
        _metricas_item_cache[clave_cache] = {"data": resultado, "timestamp": time.time()}
        return resultado

    headers = {"Authorization": f"Bearer {access_token}", "Api-Version": "2"}

    def _consultar_uno(item_id):
        url = (
            f"https://api.mercadolibre.com/marketplace/advertising/{site_id}/product_ads/ads/{item_id}"
            f"?date_from={fecha_desde}&date_to={fecha_hasta}&metrics=cost,total_amount,units_quantity,clicks,prints"
        )
        try:
            resp = meli_http.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return item_id, None
            data = resp.json()
            m = data.get("metrics", {}) or {}
            costo = float(m.get("cost") or 0.0)
            prints = int(m.get("prints") or 0)
            if costo <= 0 and prints <= 0:
                return item_id, None
            return item_id, {
                "costo": costo, "ventas": float(m.get("total_amount") or 0.0), "unidades": int(m.get("units_quantity") or 0),
                "clicks": int(m.get("clicks") or 0), "prints": prints,
                "titulo": data.get("title"), "thumbnail": (data.get("thumbnail") or "").replace("http://", "https://") or None,
            }
        except Exception as e:
            print(f"[Ads] ⚠️ Error consultando métricas de {item_id}: {e}")
            return item_id, None

    resultado = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for item_id, datos in executor.map(_consultar_uno, ids_relevantes):
            if datos is not None:
                resultado[item_id] = datos

    _metricas_item_cache[clave_cache] = {"data": resultado, "timestamp": time.time()}
    return resultado


class CostosAds(dict):
    """
    Costo de publicidad por publicación ({id_meli: costo}). `incompleto` = a cuántas publicaciones Mercado Libre NO les contestó (límite de pedidos, caída, permisos): se omiten y cuentan como
    «sin gasto», así que la ganancia podría salir sobrestimada. Quien lo muestra tiene que avisarlo. Es un dict común para el resto del código.
    """
    incompleto = 0


def obtener_costos_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_relevantes, site_id="MLA"):
    clave_cache = (advertiser_id, fecha_desde, fecha_hasta, tuple(sorted(ids_relevantes)))
    cacheado = _costos_cache.get(clave_cache)
    if cacheado and (time.time() - cacheado["timestamp"]) < TTL_COSTOS_SEGUNDOS:
        return cacheado["data"]

    listado = obtener_anuncios_con_metricas(access_token, advertiser_id, fecha_desde, fecha_hasta, site_id)
    if listado is not None:
        relevantes = set(ids_relevantes)
        costos_por_item = CostosAds()
        costos_por_item.update({i: a["costo"] for i, a in listado.items() if i in relevantes and a["costo"] > 0})
        _costos_cache[clave_cache] = {"data": costos_por_item, "timestamp": time.time()}
        return costos_por_item

    headers = {"Authorization": f"Bearer {access_token}", "Api-Version": "2"}
    costos_por_item = CostosAds()

    def _consultar_uno(item_id):
        """(id, costo o None, ¿falló?). 200 = el costo (0 es «sin gasto»); 404 = la publicación no tiene anuncio (normal); cualquier otra respuesta o un corte es un FALLO, no «sin gasto»."""
        url = (
            f"https://api.mercadolibre.com/marketplace/advertising/{site_id}/product_ads/ads/{item_id}"
            f"?date_from={fecha_desde}&date_to={fecha_hasta}&metrics=cost"
        )
        try:
            resp = meli_http.get(url, headers=headers, timeout=8)
            if resp.status_code == 404:
                return item_id, None, False
            if resp.status_code != 200:
                return item_id, None, True
            data = resp.json()
            costo = float((data.get("metrics", {}) or {}).get("cost") or 0.0)
            return item_id, (costo if costo > 0 else None), False
        except Exception as e:
            print(f"[Ads] ⚠️ Error consultando costo de {item_id}: {e}")
            return item_id, None, True

    fallos = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for item_id, costo, fallo in executor.map(_consultar_uno, ids_relevantes):
            fallos += 1 if fallo else 0
            if costo is not None:
                costos_por_item[item_id] = costo

    costos_por_item.incompleto = fallos
    if fallos:
        print(f"[Ads] ⚠️ No se pudo leer el costo de publicidad de {fallos} publicación(es): la ganancia puede salir sobrestimada y el resultado NO se guarda en caché.")
    else:
        _costos_cache[clave_cache] = {"data": costos_por_item, "timestamp": time.time()}     # un resultado a medias no se guarda: se volvería a mostrar durante 5 minutos
    return costos_por_item

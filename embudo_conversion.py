"""
Embudo de Conversión — portado de Santi Mens. Bug de fuga entre
cuentas encontrado (misma familia que en ads.py, facturacion.py,
logistica.py y tendencias.py): `_cache_embudo` y `_cache_zombies` eran
sendos slots globales únicos — la primera cuenta que consultara dejaba
SU embudo/zombies cacheado para cualquier otra cuenta que consultara
después. Ahora ambas cachés se indexan por cuenta_id.
"""
import requests
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

_cache_embudo = {}
_cache_zombies = {}
TTL_SEGUNDOS = 900


def obtener_visitas_items(headers, ids_lista, date_from, date_to):
    if not ids_lista:
        return {}
    ids_param = ",".join(ids_lista)
    try:
        resp = requests.get(
            "https://api.mercadolibre.com/items/visits",
            headers=headers, params={"ids": ids_param, "date_from": date_from, "date_to": date_to}, timeout=10
        )
        if resp.status_code != 200:
            print(f"[Embudo] ⚠️ Error consultando visitas: {resp.status_code} - {resp.text[:200]}")
            return {}
        data = resp.json()
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            resultado = {}
            for fila in data:
                id_item = fila.get("item_id") or fila.get("id")
                visitas = fila.get("total_visits") or fila.get("visits") or fila.get("quantity") or 0
                if id_item:
                    resultado[id_item] = visitas
            return resultado
    except Exception as e:
        print(f"[Embudo] ❌ Error de conexión consultando visitas: {e}")
    return {}


def _obtener_cantidad_preguntas(headers, id_meli):
    try:
        resp = requests.get("https://api.mercadolibre.com/questions/search", params={"item": id_meli, "limit": 1}, headers=headers, timeout=6)
        if resp.status_code == 200:
            return resp.json().get("total", 0)
    except Exception as e:
        print(f"[Embudo] ⚠️ Error consultando preguntas de {id_meli}: {e}")
    return 0


def detectar_publicaciones_zombie(headers, cuenta_id, cursor, dias=60):
    ahora = time.time()
    cacheado = _cache_zombies.get(cuenta_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    fecha_hasta = datetime.now().strftime("%Y-%m-%d")
    fecha_desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    cursor.execute("SELECT id_meli, titulo, thumbnail FROM productos_padre WHERE estado = 'active'")
    activos = cursor.fetchall()
    if not activos:
        return []

    ids_lista = [a[0] for a in activos]
    visitas_por_item = obtener_visitas_items(headers, ids_lista, fecha_desde, fecha_hasta)

    cursor.execute("SELECT DISTINCT id_meli FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde, fecha_hasta))
    ids_con_venta = {row[0] for row in cursor.fetchall()}

    zombies = []
    for id_meli, titulo, thumbnail in activos:
        visitas = visitas_por_item.get(id_meli, 0)
        if visitas == 0 and id_meli not in ids_con_venta:
            zombies.append({"id_meli": id_meli, "titulo": titulo, "thumbnail": thumbnail})

    _cache_zombies[cuenta_id] = {"data": zombies, "timestamp": ahora}
    return zombies


def calcular_embudo_conversion(headers, cuenta_id, cursor, dias=30):
    ahora = time.time()
    cacheado = _cache_embudo.get(cuenta_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    fecha_hasta = datetime.now().strftime("%Y-%m-%d")
    fecha_desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active'")
    activos = cursor.fetchall()
    if not activos:
        return []

    ids_lista = [a[0] for a in activos]
    visitas_por_item = obtener_visitas_items(headers, ids_lista, fecha_desde, fecha_hasta)

    cursor.execute("SELECT id_meli, COALESCE(SUM(cantidad), 0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s GROUP BY id_meli", (fecha_desde, fecha_hasta))
    ventas_por_item = dict(cursor.fetchall())

    preguntas_por_item = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(_obtener_cantidad_preguntas, headers, id_meli): id_meli for id_meli, _ in activos}
        for futuro in as_completed(futuros):
            id_meli = futuros[futuro]
            try:
                preguntas_por_item[id_meli] = futuro.result()
            except Exception:
                preguntas_por_item[id_meli] = 0

    resultado = []
    for id_meli, titulo in activos:
        visitas = visitas_por_item.get(id_meli, 0) or 0
        preguntas = preguntas_por_item.get(id_meli, 0)
        vendidas = ventas_por_item.get(id_meli, 0)
        tasa_conversion = round((vendidas / visitas) * 100, 2) if visitas > 0 else None
        if visitas == 0:
            diagnostico = "sin_datos"
        elif tasa_conversion is not None and tasa_conversion < 1:
            diagnostico = "revisar_ficha"
        elif visitas < 50:
            diagnostico = "poca_visibilidad"
        else:
            diagnostico = "funciona_bien"

        resultado.append({
            "id_meli": id_meli, "titulo": titulo, "visitas": visitas, "preguntas": preguntas,
            "vendidas": vendidas, "tasa_conversion": tasa_conversion, "diagnostico": diagnostico
        })

    def _prioridad(r):
        if r["diagnostico"] == "revisar_ficha":
            return (0, -r["visitas"])
        if r["diagnostico"] == "poca_visibilidad":
            return (1, -r["visitas"])
        return (2, -r["visitas"])
    resultado.sort(key=_prioridad)

    _cache_embudo[cuenta_id] = {"data": resultado, "timestamp": ahora}
    return resultado

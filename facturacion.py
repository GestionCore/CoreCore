"""
Facturación — portado de Santi Mens.

Mismo tipo de bug que encontré en ads.py: `_cache_periodos` era un
ÚNICO slot global (ni siquiera por cuenta), y `_cache_resumenes` cacheaba
por período (ej: "2026-09") sin cuenta_id — dos cuentas consultando el
mismo mes se hubieran pisado los resúmenes de facturación entre sí.
Ambas cachés ahora incluyen cuenta_id en su clave.
"""
import time
import requests

BASE_URL = "https://api.mercadolibre.com/billing/integration"

_cache_periodos = {}
_cache_resumenes = {}
TTL_SEGUNDOS = 600  # 10 minutos


def obtener_periodos(access_token, cuenta_id, group="ML"):
    ahora = time.time()
    cacheado = _cache_periodos.get(cuenta_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(f"{BASE_URL}/monthly/periods", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            resultado = data if isinstance(data, list) else data.get("results", [])
            _cache_periodos[cuenta_id] = {"data": resultado, "timestamp": ahora}
            return resultado
        print(f"[Facturación] ⚠️ No se pudieron traer los períodos: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        print(f"[Facturación] ❌ Error de conexión: {e}")

    return cacheado["data"] if cacheado else []


def obtener_resumen_periodo(access_token, cuenta_id, key, group="ML"):
    ahora = time.time()
    clave = (cuenta_id, group, key)
    cacheado = _cache_resumenes.get(clave)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(f"{BASE_URL}/periods/key/{key}/summary/details", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            _cache_resumenes[clave] = {"data": data, "timestamp": ahora}
            return data
        print(f"[Facturación] ⚠️ No se pudo traer el resumen del período {key}: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        print(f"[Facturación] ❌ Error de conexión: {e}")

    return cacheado["data"] if cacheado else None


def obtener_costo_almacenamiento_full(access_token, period_key, group="ML"):
    """
    Busca cargos de almacenamiento prolongado en FULL dentro del detalle de
    conciliación de un período mensual. MeLi no documenta un código de
    cargo estable para esto, así que buscamos por el texto legible del
    cargo (transaction_detail) — si no encuentra nada, no significa
    necesariamente que no haya cargo, conviene confirmar con un período
    real que sepas que tuvo este cargo.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    palabras_clave = ["almacenamiento", "storage", "stock antiguo", "bodega"]
    total = 0.0
    cantidad = 0
    try:
        resp = requests.get(
            f"{BASE_URL}/periods/key/{period_key}/group/{group}/details",
            headers=headers, params={"document_type": "BILL", "detail_type": "charge", "limit": 100}, timeout=15
        )
        if resp.status_code != 200:
            print(f"[Facturación] ⚠️ No se pudo traer el detalle de conciliación: {resp.status_code} - {resp.text[:300]}")
            return None, 0
        data = resp.json()
        resultados = data if isinstance(data, list) else data.get("results", [])
        for detalle in resultados:
            info = detalle.get("charge_info", {}) or {}
            texto = (info.get("transaction_detail") or "").lower()
            if any(palabra in texto for palabra in palabras_clave):
                total += float(info.get("detail_amount", 0) or 0)
                cantidad += 1
        return round(total, 2), cantidad
    except Exception as e:
        print(f"[Facturación] ❌ Error buscando costo de almacenamiento: {e}")
        return None, 0

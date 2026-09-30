"""
Facturación — portado de Santi Mens.

Mismo tipo de bug que encontré en ads.py: `_cache_periodos` era un
ÚNICO slot global (ni siquiera por cuenta), y `_cache_resumenes` cacheaba
por período (ej: "2026-09") sin cuenta_id — dos cuentas consultando el
mismo mes se hubieran pisado los resúmenes de facturación entre sí.
Ambas cachés ahora incluyen cuenta_id en su clave.
"""
import time
import meli_http
from utils import formatear_moneda

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
        resp = meli_http.get(f"{BASE_URL}/monthly/periods", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=10)
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
        resp = meli_http.get(f"{BASE_URL}/periods/key/{key}/summary/details", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            _cache_resumenes[clave] = {"data": data, "timestamp": ahora}
            return data
        print(f"[Facturación] ⚠️ No se pudo traer el resumen del período {key}: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        print(f"[Facturación] ❌ Error de conexión: {e}")

    return cacheado["data"] if cacheado else None


_cache_almacenamiento = {}


def obtener_costo_almacenamiento_full(access_token, cuenta_id, period_key, group="ML"):
    """
    Busca cargos de almacenamiento prolongado en FULL dentro del detalle de
    conciliación de un período mensual. MeLi no documenta un código de
    cargo estable para esto, así que buscamos por el texto legible del
    cargo (transaction_detail) — si no encuentra nada, no significa
    necesariamente que no haya cargo, conviene confirmar con un período
    real que sepas que tuvo este cargo.

    Cacheado 10 min por cuenta — antes se pedía sin caché en cada carga
    de /metricas (vía comparador_logistica), sumando una llamada extra
    a la API en cada visita a la página aunque el período no hubiera
    cambiado. cuenta_id va en la clave del caché a propósito: la misma
    familia de bug que ya se corrigió en ads.py y acá mismo (arriba,
    _cache_periodos/_cache_resumenes) — sin cuenta_id, dos cuentas
    consultando el mismo period_key se pisarían el resultado.
    """
    ahora = time.time()
    clave = (cuenta_id, group, period_key)
    cacheado = _cache_almacenamiento.get(clave)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    palabras_clave = ["almacenamiento", "storage", "stock antiguo", "bodega"]
    total = 0.0
    cantidad = 0
    try:
        resp = meli_http.get(
            f"{BASE_URL}/periods/key/{period_key}/group/{group}/details",
            headers=headers, params={"document_type": "BILL", "detail_type": "charge", "limit": 100}, timeout=15
        )
        if resp.status_code != 200:
            print(f"[Facturación] ⚠️ No se pudo traer el detalle de conciliación: {resp.status_code} - {resp.text[:300]}")
            return cacheado["data"] if cacheado else (None, 0)
        data = resp.json()
        resultados = data if isinstance(data, list) else data.get("results", [])
        for detalle in resultados:
            info = detalle.get("charge_info", {}) or {}
            texto = (info.get("transaction_detail") or "").lower()
            if any(palabra in texto for palabra in palabras_clave):
                total += float(info.get("detail_amount", 0) or 0)
                cantidad += 1
        resultado = (round(total, 2), cantidad)
        _cache_almacenamiento[clave] = {"data": resultado, "timestamp": ahora}
        return resultado
    except Exception as e:
        print(f"[Facturación] ❌ Error buscando costo de almacenamiento: {e}")
        return cacheado["data"] if cacheado else (None, 0)


def resumen_condensado_periodo_actual(access_token, cuenta_id, group="ML"):
    """
    Versión liviana de obtener_resumen_periodo pensada para paneles que
    solo necesitan un vistazo del período de facturación EN CURSO (no
    la página completa de /facturacion, que deja elegir un período
    viejo). Reutiliza el mismo caché de 10 minutos — si ya se visitó
    /facturacion en esta sesión, esto no pega de nuevo a la API.
    """
    periodos = obtener_periodos(access_token, cuenta_id, group)
    if not periodos:
        return None
    periodo_actual = periodos[0]
    key = periodo_actual.get("key")
    if not key:
        return None
    resumen = obtener_resumen_periodo(access_token, cuenta_id, key, group)
    if not resumen or not isinstance(resumen, dict):
        return None

    bill_includes = resumen.get("bill_includes", {})
    cargos_dict = {}
    total_cargos = 0.0
    for c in bill_includes.get("charges", []):
        categoria = (c.get("group_description") or "Otros cargos").strip()
        monto = c.get("amount") or 0.0
        cargos_dict[categoria] = cargos_dict.get(categoria, 0.0) + monto
        total_cargos += monto
    for b in bill_includes.get("bonuses", []):
        categoria = (b.get("group_description") or "Bonificaciones y anulaciones").strip()
        monto = b.get("amount") or 0.0
        cargos_dict[categoria] = cargos_dict.get(categoria, 0.0) + monto
        total_cargos += monto

    cargos = sorted(
        [{"label": k, "monto_formateado": formatear_moneda(v)} for k, v in cargos_dict.items()],
        key=lambda x: -abs(cargos_dict[x["label"]])
    )
    periodo = periodo_actual.get("period", {})
    return {
        "cargos": cargos,
        "total_cargos_formateado": formatear_moneda(total_cargos),
        "en_curso": periodo_actual.get("period_status") == "OPEN",
        "date_from": periodo.get("date_from"),
        "date_to": periodo.get("date_to"),
    }

"""
Horarios de despacho reales de la cuenta — cada vendedor tiene un horario
de corte distinto según cómo lo tenga configurado en Mercado Libre, así
que lo consultamos en vez de asumir un horario fijo para todos.
"""
import time
import meli_http

DIAS_SEMANA_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_cache_flex_habilitado = {}
TTL_SEGUNDOS = 6 * 3600  # el horario de corte casi no cambia, cacheamos varias horas


def obtener_horario_semanal(access_token, user_id, logistic_type="drop_off"):
    """
    El horario de corte de TODA la semana que informa Mercado Libre para ese tipo de logística: ('ok', {dia: «HH:MM» | None}), ('no_tiene', None) si MeLi responde 404
    (la cuenta no tiene ese servicio: es el caso de Flex/self_service, que nunca informa horario) o ('error', None) si no se pudo consultar (no es una respuesta: no se guarda).
    """
    import despacho_corte
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/users/{user_id}/shipping/schedule/{logistic_type}", headers={"Authorization": f"Bearer {access_token}"}, timeout=8)
    except Exception as e:
        print(f"[Logística] ⚠️ No se pudo consultar el horario semanal de {logistic_type}: {e}")
        return "error", None
    if resp.status_code == 404:
        return "no_tiene", None
    if resp.status_code != 200:
        print(f"[Logística] ⚠️ Horario semanal de {logistic_type}: {resp.status_code} - {resp.text[:200]}")
        return "error", None
    return "ok", despacho_corte.semana_desde_schedule(resp.json())


def tiene_flex_habilitado(access_token, site_id, user_id):
    """
    Chequea si el vendedor tiene una suscripción activa a Mercado Envíos
    Flex. Solo un 404 confirma de verdad "no tiene Flex" — cualquier otro
    código de error (401/403/429/5xx) o timeout es un problema transitorio
    de la API, no una respuesta real, así que NO se cachea como "no tiene":
    antes se cacheaba cualquier respuesta que no fuera 200 como "false" por
    TTL_SEGUNDOS (6 horas), así que un solo hipo de la API dejaba mostrando
    el cartel de "no tenés Flex" a un vendedor que sí lo tiene, por horas.
    Ante la duda (sin cache previo) se asume que SÍ tiene, para no afirmar
    algo falso — a lo sumo no se muestra un aviso informativo de más.
    """
    ahora = time.time()
    cacheado = _cache_flex_habilitado.get(user_id)
    if cacheado is not None and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        # OJO con la ruta: es /flex/sites/..., sin /shipping — con /shipping/flex/... MeLi responde 404 SIEMPRE, y este chequeo le
        # decía "no tenés Flex" a vendedores que sí lo tienen.
        resp = meli_http.get(f"https://api.mercadolibre.com/flex/sites/{site_id}/users/{user_id}/subscriptions/v1", headers=headers, timeout=8)
        if resp.status_code == 200:
            habilitado = any(s.get("mode") == "FLEX" and s.get("status") == "in" for s in (resp.json() or []))
            _cache_flex_habilitado[user_id] = {"data": habilitado, "timestamp": ahora}
            return habilitado
        if resp.status_code == 404:
            _cache_flex_habilitado[user_id] = {"data": False, "timestamp": ahora}
            return False
        print(f"[Logística] ⚠️ Respuesta inesperada chequeando Flex: {resp.status_code}")
        return (cacheado or {}).get("data", True)
    except Exception as e:
        print(f"[Logística] ❌ Error chequeando Flex: {e}")
        return (cacheado or {}).get("data", True)

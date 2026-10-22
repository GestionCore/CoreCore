"""
Consulta de varias publicaciones a la vez (multiget), con el endpoint nuevo de Mercado Libre y respaldo al viejo.

Mercado Libre retira `GET /items?ids=` y `GET /users?ids=` el 25/10/2026 (documentación «Ítems y búsquedas», actualizada el 10/09/2026): el reemplazo es `GET /items/bulk?ids=`.
Lo que cambia con el endpoint nuevo (verificado contra Mercado Libre real el 2026-10-21, desde una máquina de producción y con publicaciones propias):
  · cada elemento es `{id, status_code, body}`; si la publicación no existe, `{id, status_code: 404, error: {...}}` (sin `body`);
  · los campos que se piden con `attributes=` llevan el prefijo `body.`, y **la raíz se pierde si no se pide**: con `attributes=body.id,body.title` cada elemento llega solo como `{body: {...}}` y una
    publicación inexistente como `{}` (no se sabe qué pasó). Por eso se piden también `id,status_code`: `attributes=id,status_code,body.id,body.title`;
  · máximo 20 ids por pedido (con 21, 400 «Too many IDs. Maximum allowed: 20»); `include_attributes=all` es aceptado.
El viejo `/items?ids=` (también 20 como máximo) responde hasta el 25/10/2026. Este módulo acepta las dos formas de elemento y, si el endpoint nuevo no está o contesta algo que no es una lista, vuelve al viejo.

Cada elemento de salida es `{"id", "status_code", "body", "error"}`, sea cual sea el endpoint que contestó. Cómo ver cuál se usa en producción: `fly logs -a corecore | grep ItemsBulk`.
"""
import time

import meli_http

URL_BULK = "https://api.mercadolibre.com/items/bulk"
URL_VIEJA = "https://api.mercadolibre.com/items"
LOTE_MAXIMO = 20
PREFIJO_BULK = "body."
RAIZ_BULK = ("id", "status_code")
SIN_ENDPOINT = (404, 405, 410, 501)            # el endpoint nuevo todavía no está (o ya no): no se insiste durante un rato
RECHAZO_POR_FORMATO = (400,)                   # puede ser el formato del pedido nuevo: se prueba el viejo, pero no se descarta el nuevo
ESPERA_TRAS_SIN_ENDPOINT = 30 * 60

# Capacidad de la API (igual para todas las cuentas): hasta cuándo se saltea el endpoint nuevo porque respondió «no existe». Un solo valor, sin datos de ninguna cuenta.
_ESTADO = {"bulk_saltear_hasta": 0.0, "avisado": set()}


def _avisar_una_vez(clave, texto):
    """Una línea en los logs la primera vez que pasa algo (cuál endpoint se usa, cuándo se vuelve al viejo), no una por lote."""
    if clave not in _ESTADO["avisado"]:
        _ESTADO["avisado"].add(clave)
        print(f"[ItemsBulk] {texto}")


def _normalizar(datos):
    """
    Una lista de elementos con la forma vieja ({code, body}) o la nueva ({id, status_code, body}) → [{id, status_code, body}].
    Devuelve None si no es una lista de eso (para que quien llama pruebe el otro endpoint).
    """
    if not isinstance(datos, list):
        return None
    elementos = []
    for fila in datos:
        if not isinstance(fila, dict):
            return None
        cuerpo = fila.get("body")
        cuerpo = cuerpo if isinstance(cuerpo, dict) else None
        estado = fila.get("status_code", fila.get("code"))
        if isinstance(estado, bool) or not isinstance(estado, int):
            estado = 200 if cuerpo else 0                      # un elemento filtrado por `attributes` llega solo con `body`: si hay cuerpo es que salió bien; si no, no se sabe qué pasó
        identificador = fila.get("id") or (cuerpo or {}).get("id")
        elementos.append({"id": identificador, "status_code": estado, "body": cuerpo, "error": fila.get("error")})
    if elementos and all(e["status_code"] == 0 for e in elementos):
        return None                                            # ningún elemento dice nada (p. ej. `attributes=id,title` sin prefijo llega solo con `id`): no es una respuesta usable, se prueba el viejo
    return elementos


def _json(respuesta):
    try:
        return respuesta.json()
    except ValueError:
        return None


def _url(base, lote, atributos, prefijo):
    """La dirección con la consulta escrita a mano (las comas sin codificar), igual que la que usaba el sincronizador desde siempre."""
    direccion = f"{base}?ids={','.join(lote)}"
    if atributos:
        campos = [f"{prefijo}{a}" for a in atributos]
        if prefijo:
            campos = list(RAIZ_BULK) + campos                  # el endpoint nuevo pierde `id` y `status_code` si se filtra solo por `body.`: se piden aparte
        direccion += "&attributes=" + ",".join(campos)
    return direccion


def _traer_lote(lote, headers, atributos, timeout):
    """(estado, elementos, texto_del_error) de un lote de hasta 20 ids."""
    if time.monotonic() >= _ESTADO["bulk_saltear_hasta"]:
        respuesta = meli_http.get(_url(URL_BULK, lote, atributos, PREFIJO_BULK), headers=headers, timeout=timeout)
        if respuesta.status_code == 200:
            elementos = _normalizar(_json(respuesta))
            if elementos is not None:
                _avisar_una_vez("bulk_ok", "se usa /items/bulk.")
                return 200, elementos, ""
            _avisar_una_vez("bulk_forma", f"/items/bulk respondió 200 con una forma inesperada ({respuesta.text[:120]!r}); se usa el endpoint viejo.")
        elif respuesta.status_code in SIN_ENDPOINT:
            _ESTADO["bulk_saltear_hasta"] = time.monotonic() + ESPERA_TRAS_SIN_ENDPOINT
            _avisar_una_vez("bulk_ausente", f"/items/bulk respondió {respuesta.status_code}; se usa el endpoint viejo y se vuelve a probar en media hora.")
        elif respuesta.status_code in RECHAZO_POR_FORMATO:
            _avisar_una_vez("bulk_400", f"/items/bulk rechazó el pedido (400: {respuesta.text[:120]!r}); se usa el endpoint viejo.")
        else:
            return respuesta.status_code, [], respuesta.text[:160]               # 401, 403, 429, 5xx…: el viejo daría lo mismo
    respuesta = meli_http.get(_url(URL_VIEJA, lote, atributos, ""), headers=headers, timeout=timeout)
    if respuesta.status_code != 200:
        return respuesta.status_code, [], respuesta.text[:160]
    elementos = _normalizar(_json(respuesta))
    if elementos is None:
        return 200, [], f"respuesta que no es una lista de publicaciones: {respuesta.text[:120]!r}"
    _avisar_una_vez("viejo_ok", "se usa el endpoint viejo /items?ids= (deja de existir el 25/10/2026).")
    return 200, elementos, ""


def traer_items(ids, headers, atributos=None, timeout=10):
    """
    Trae las publicaciones `ids` de a 20. `atributos` = campos del cuerpo que se quieren (sin prefijo: «id», «title»…; este módulo agrega `body.` donde corresponde); sin ellos, el cuerpo completo.
    Devuelve (elementos, fallos): `elementos` son los de todos los lotes que respondieron; `fallos`, una tupla (cantidad_de_ids, estado, texto) por cada lote que no respondió bien.
    Un lote fallido no corta a los demás. Un error de conexión (excepción) sí se propaga, como antes.
    """
    ids = [i for i in dict.fromkeys(ids or []) if i]
    elementos, fallos = [], []
    for desde in range(0, len(ids), LOTE_MAXIMO):
        lote = ids[desde:desde + LOTE_MAXIMO]
        estado, parte, texto = _traer_lote(lote, headers, atributos, timeout)
        if estado == 200 and not texto:
            elementos.extend(parte)
        else:
            fallos.append((len(lote), estado, texto))
    return elementos, fallos

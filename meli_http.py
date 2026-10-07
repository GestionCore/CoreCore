"""
Cliente HTTP centralizado para hablar con la API de Mercado Libre, con
reintentos automáticos ante 429 (límite de requests) y caídas momentáneas
(5xx), con espera creciente entre intentos. Uso: reemplazar
"requests.get(url, ...)" por "meli_http.get(url, ...)" — misma firma,
mismo objeto de respuesta, solo que ahora no se rinde al primer tropiezo.

Antes de esto, cada módulo llamaba a requests.get/put directo, así que
un 429 puntual de MeLi cortaba esa sincronización sin más.

Dos reglas de seguridad:
  · Un POST NO se reintenta solo: si Mercado Libre lo procesó y falló al responder, repetirlo duplicaría la acción (una respuesta, una promoción).
    GET, PUT y DELETE sí: repetirlos da el mismo resultado.
  · Si Mercado Libre sigue rechazando después de los reintentos (429/5xx), TODOS los hilos del proceso esperan un momento antes de insistir
    (PAUSA_TRAS_RECHAZO) en vez de que cada uno siga golpeando por su cuenta. No hay un límite de pedidos por segundo inventado: las medidas
    reales muestran que MeLi acepta el ritmo de una sincronización (unos 12 pedidos por segundo por cuenta) sin rechazar.
"""
import threading
import time

import requests

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    def _crear_sesion():
        sesion = requests.Session()
        try:
            reintento = Retry(
                total=3,
                backoff_factor=1.5,  # espera ~1.5s, 3s, 6s entre intentos
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "PUT", "DELETE"],
                respect_retry_after_header=True,
            )
        except TypeError:
            # Versiones más viejas de urllib3 usan "method_whitelist" en vez
            # de "allowed_methods" — este fallback cubre esa diferencia.
            reintento = Retry(
                total=3,
                backoff_factor=1.5,
                status_forcelist=[429, 500, 502, 503, 504],
                method_whitelist=["GET", "PUT", "DELETE"],
            )
        adaptador = HTTPAdapter(max_retries=reintento)
        sesion.mount("https://", adaptador)
        sesion.mount("http://", adaptador)
        return sesion

    _sesion = _crear_sesion()
except Exception as e:
    print(f"[meli_http] ⚠️ No se pudo configurar reintentos automáticos, seguimos sin ellos: {e}")
    _sesion = requests.Session()


PAUSA_TRAS_RECHAZO = 20.0           # segundos que esperan todos los hilos después de que MeLi rechaza aun con reintentos
_pausa = {"hasta": 0.0}
_candado = threading.Lock()


def _respetar_pausa():
    espera = _pausa["hasta"] - time.monotonic()
    if espera > 0:
        time.sleep(min(espera, PAUSA_TRAS_RECHAZO))


respetar_pausa = _respetar_pausa           # para quien llama a MeLi sin pasar por acá (auth.token_manager.llamar_api_meli)

# Freno por cabeceras. Mercado Libre NO manda cabeceras de límite en sus respuestas normales (se miraron 6 respuestas reales: ninguna), así que esto es una red de
# seguridad: si algún día las manda (o responde 429/503 con Retry-After), todos los hilos del proceso esperan a que se renueve el cupo en vez de seguir
# disparando hasta recibir el rechazo. El límite es de la aplicación, no de una cuenta: la pausa es global a propósito y no guarda datos de ninguna cuenta.
REMANENTE_MINIMO = 2
_CAB_REMANENTE = ("x-ratelimit-remaining", "x-rate-limit-remaining", "ratelimit-remaining")
_CAB_REINICIO = ("x-ratelimit-reset", "x-rate-limit-reset", "ratelimit-reset", "retry-after")


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def espera_segun_cabeceras(estado, cabeceras):
    """Segundos que conviene esperar según lo que informa la respuesta, o 0. `x-ratelimit-reset` puede venir como segundos que faltan o como hora epoch."""
    cab = {str(k).lower(): v for k, v in (cabeceras or {}).items()}
    restante = next((n for n in (_numero(cab[c]) for c in _CAB_REMANENTE if c in cab) if n is not None), None)
    reinicio = next((n for n in (_numero(cab[c]) for c in _CAB_REINICIO if c in cab) if n is not None), None)
    if reinicio is not None and reinicio > 10_000_000:                   # hora epoch, no segundos
        reinicio = reinicio - time.time()
    if reinicio is None or reinicio <= 0:
        return PAUSA_TRAS_RECHAZO if estado == 429 else 0.0
    if estado in (429, 503) or (restante is not None and restante <= REMANENTE_MINIMO):
        return min(reinicio, PAUSA_TRAS_RECHAZO)
    return 0.0


def frenar_segun_cabeceras(resp):
    espera = espera_segun_cabeceras(getattr(resp, "status_code", None), getattr(resp, "headers", None))
    if espera > 0:
        with _candado:
            _pausa["hasta"] = max(_pausa["hasta"], time.monotonic() + espera)
    return resp


def _pedir(metodo, url, kwargs):
    kwargs.setdefault("timeout", 15)
    _respetar_pausa()
    try:
        return frenar_segun_cabeceras(getattr(_sesion, metodo)(url, **kwargs))
    except requests.exceptions.RetryError:
        with _candado:
            _pausa["hasta"] = time.monotonic() + PAUSA_TRAS_RECHAZO
        raise


def get(url, **kwargs):
    return _pedir("get", url, kwargs)


def put(url, **kwargs):
    return _pedir("put", url, kwargs)


def post(url, **kwargs):
    return _pedir("post", url, kwargs)


def delete(url, **kwargs):
    return _pedir("delete", url, kwargs)

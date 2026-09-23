"""
Cliente HTTP centralizado para hablar con la API de Mercado Libre, con
reintentos automáticos ante 429 (límite de requests) y caídas momentáneas
(5xx), con espera creciente entre intentos. Uso: reemplazar
"requests.get(url, ...)" por "meli_http.get(url, ...)" — misma firma,
mismo objeto de respuesta, solo que ahora no se rinde al primer tropiezo.

Antes de esto, cada módulo llamaba a requests.get/put directo, así que
un 429 puntual de MeLi cortaba esa sincronización sin más.
"""
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
                allowed_methods=["GET", "PUT", "POST", "DELETE"],
                respect_retry_after_header=True,
            )
        except TypeError:
            # Versiones más viejas de urllib3 usan "method_whitelist" en vez
            # de "allowed_methods" — este fallback cubre esa diferencia.
            reintento = Retry(
                total=3,
                backoff_factor=1.5,
                status_forcelist=[429, 500, 502, 503, 504],
                method_whitelist=["GET", "PUT", "POST", "DELETE"],
            )
        adaptador = HTTPAdapter(max_retries=reintento)
        sesion.mount("https://", adaptador)
        sesion.mount("http://", adaptador)
        return sesion

    _sesion = _crear_sesion()
except Exception as e:
    print(f"[meli_http] ⚠️ No se pudo configurar reintentos automáticos, seguimos sin ellos: {e}")
    _sesion = requests.Session()


def get(url, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _sesion.get(url, **kwargs)


def put(url, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _sesion.put(url, **kwargs)


def post(url, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _sesion.post(url, **kwargs)


def delete(url, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _sesion.delete(url, **kwargs)

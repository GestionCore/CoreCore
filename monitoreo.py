"""
Errores de las sincronizaciones con Mercado Libre que se tragan a propósito (un paso que falla no puede frenar a los demás) pero que alguien tiene que enterarse de que pasaron.
Antes solo quedaban como una línea en el log de Fly; con `SENTRY_DSN` configurado, `reportar` los manda a Sentry con la fase y la cuenta como etiquetas.

Reglas:
  · Se reporta el fallo de una FASE de la sincronización de una cuenta (catálogo, ventas, reclamos, enriquecimiento…), nunca el ruido de una publicación o un envío suelto (eso es normal
    con una API que a veces no contesta y ya se reintenta solo en la próxima pasada).
  · Los eventos de la misma fase y el mismo tipo de error se agrupan en UN problema de Sentry (no uno por cuenta) y no se repiten más de una vez cada 10 minutos por cuenta: una caída de
    Mercado Libre no puede gastar los 5.000 eventos mensuales del plan gratis en una hora.
  · Solo viajan la fase, el número de cuenta y el error: ningún token, email, ni dato de ventas.
  · `reportar` NUNCA levanta una excepción ni demora la sincronización (sin Sentry configurado vuelve al instante).
"""
import threading
import time

SEGUNDOS_ENTRE_REPORTES = 600
_ultimos = {}          # (fase, cuenta_id, tipo de error) -> instante del último reporte; clave con la cuenta; se vacía al pasar de 500 entradas
_lock = threading.Lock()


def _toca_reportar(clave, ahora):
    with _lock:
        previo = _ultimos.get(clave)
        if previo is not None and ahora - previo < SEGUNDOS_ENTRE_REPORTES:
            return False
        if len(_ultimos) > 500:
            _ultimos.clear()
        _ultimos[clave] = ahora
        return True


def reportar(fase, error, cuenta_id=None, ahora=None):
    """Manda a Sentry el fallo de `fase` (p. ej. «ventas», «catalogo») de la cuenta `cuenta_id`. True si lo mandó."""
    try:
        import sentry_sdk
        cliente = sentry_sdk.get_client()
        if not cliente.is_active() or not getattr(cliente, "dsn", None):          # sin DSN no hay a dónde mandar nada
            return False
        if not _toca_reportar((fase, cuenta_id, type(error).__name__), time.monotonic() if ahora is None else ahora):
            return False
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("fase", fase)
            if cuenta_id is not None:
                scope.set_tag("cuenta_id", str(cuenta_id))
            scope.fingerprint = ["sincronizacion", fase, type(error).__name__]
            sentry_sdk.capture_exception(error)
        return True
    except Exception:
        return False

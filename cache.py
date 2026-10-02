"""
Instancia única de Flask-Caching para CoreLux.

Vive en su propio módulo para evitar imports circulares: cualquier
módulo que necesite cachear puede hacer `from cache import cache` sin
importar app.py. La inicialización real (`cache.init_app(app)`) ocurre
en app.py después de crear la app de Flask.

Estrategia de keys:
  El prefijo `corelux_` más `(usuario_id, cuenta_id, *params)` garantiza
  aislamiento entre cuentas — nunca puede filtrarse el cache de una cuenta
  a otra aunque el servidor Redis sea compartido.

Fallback automático:
  Si Redis no está disponible al arrancar, app.py usa SimpleCache (en memoria del proceso): sin esto cada cache.get() lanzaba ConnectionError y
  rompía las páginas (Fly no tiene Redis). Con varios procesos cada uno tiene su propia copia, así que NO se guarda acá nada que tenga que
  coincidir entre procesos (para eso está cache_db).

  Aunque Redis se caiga con la app andando, usar leer()/guardar() en vez de cache.get()/cache.set(): una caché que falla nunca debe romper la página.
"""
import logging

from flask_caching import Cache

cache = Cache()
log = logging.getLogger("corelux.cache")


def leer(clave):
    """El valor guardado o None; si la caché falla, None (la página lo calcula como si no hubiera caché)."""
    try:
        return cache.get(clave)
    except Exception as e:
        log.warning("La caché no respondió al leer '%s': %s", clave, e)
        return None


def guardar(clave, valor, timeout=None):
    try:
        cache.set(clave, valor, timeout=timeout)
    except Exception as e:
        log.warning("La caché no respondió al guardar '%s': %s", clave, e)


def construir_key(*partes):
    """Helper para armar cache keys con aislamiento garantizado por cuenta."""
    return ":".join(str(p) for p in partes)

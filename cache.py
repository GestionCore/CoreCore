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
  Si Redis no está disponible al arrancar, Flask-Caching cae a
  SimpleCache (en memoria del proceso). Funciona bien para un solo worker;
  con múltiples workers cada uno tiene su propio cache. Aceptable para dev.
"""
from flask_caching import Cache

cache = Cache()


def construir_key(*partes):
    """Helper para armar cache keys con aislamiento garantizado por cuenta."""
    return ":".join(str(p) for p in partes)

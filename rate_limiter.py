"""
Rate limiter proactivo para llamadas a la API de MeLi — token bucket
implementado sobre Redis.

meli_http.py ya tiene reintentos automáticos ante 429 (backoff 1.5x,
hasta 3 intentos). Este módulo actúa ANTES de la llamada: verifica si
hay crédito disponible. Si no hay, espera el tiempo mínimo necesario
antes de ceder el control. Así evitamos recibir el 429 en primer lugar,
que es mejor que recibirlo y retroceder.

Categorías de endpoints MeLi (límites documentados en 2024):
  - "general": 100 req/min por access_token (~1.67 req/s)
  - "search": 40 req/min por access_token (~0.67 req/s)
  - "orders": 40 req/min por access_token

Uso:
    from rate_limiter import esperar_slot
    esperar_slot(access_token, categoria="general")
    # ... llamada a la API

Si Redis no está disponible, `esperar_slot` es un no-op — la app sigue
funcionando, solo sin rate limiting proactivo (meli_http.py todavía
reintenta ante 429).
"""
import time
import logging

logger = logging.getLogger(__name__)

# Límites por categoría: (max_tokens, tokens_por_segundo)
_LIMITES = {
    "general": (100, 1.6),
    "search": (40, 0.65),
    "orders": (40, 0.65),
}

_redis_client = None


def _obtener_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        import config
        _redis_client = redis.from_url(config.REDIS_URL, socket_connect_timeout=1)
        _redis_client.ping()
        return _redis_client
    except Exception:
        return None


def esperar_slot(identificador: str, categoria: str = "general", timeout: float = 30.0):
    """
    Espera hasta que haya un slot disponible en el bucket del identificador.
    `identificador` es el access_token o client_id — lo que se quiera usar
    como clave de aislamiento del rate limit.

    Si Redis no está disponible, retorna inmediatamente (no-op).
    Si el timeout se agota antes de conseguir un slot, loguea un warning
    y retorna igual (la llamada va a proceder; meli_http.py maneja el 429).
    """
    r = _obtener_redis()
    if r is None:
        return

    max_tokens, tps = _LIMITES.get(categoria, _LIMITES["general"])
    # Usamos los primeros 16 caracteres del token como clave para no exponer
    # el token completo en Redis ni tener keys demasiado largas.
    key = f"rl:{categoria}:{identificador[:16]}"
    intervalo = 1.0 / tps
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        pipe = r.pipeline()
        ahora = time.time()
        try:
            pipe.execute_command("CL.THROTTLE", key, max_tokens - 1, max_tokens, 60)
            # CL.THROTTLE de Redis es parte del módulo RedisCell.
            # Si no está disponible, usamos el fallback de sliding window abajo.
        except Exception:
            # RedisCell no disponible — fallback a sliding window manual
            _esperar_slot_manual(r, key, max_tokens, intervalo, deadline)
            return

        try:
            result = pipe.execute()[0]
        except Exception as e:
            logger.debug(f"[RateLimiter] Redis error: {e}")
            return

        # result[0] = 0 (permitido) o 1 (rechazado)
        if result[0] == 0:
            return  # Hay slot disponible
        wait_time = result[3] / 1000.0  # milisegundos → segundos
        if time.monotonic() + wait_time > deadline:
            logger.warning(f"[RateLimiter] Timeout esperando slot para {key}")
            return
        time.sleep(min(wait_time, intervalo))


def _esperar_slot_manual(r, key: str, max_tokens: int, intervalo: float, deadline: float):
    """
    Sliding window rate limiter usando Redis ZSET.
    Alternativa cuando RedisCell (CL.THROTTLE) no está instalado.
    """
    window = 60  # ventana de 1 minuto
    while time.monotonic() < deadline:
        ahora = time.time()
        pipe = r.pipeline(transaction=True)
        try:
            pipe.zremrangebyscore(key, 0, ahora - window)
            pipe.zcard(key)
            pipe.zadd(key, {str(ahora): ahora})
            pipe.expire(key, window + 1)
            results = pipe.execute()
            count = results[1]
            if count < max_tokens:
                return  # La zadd ya registró este request
            # Remover el zadd que acabamos de hacer (no hay slot)
            r.zremrangebyscore(key, ahora, ahora)
        except Exception as e:
            logger.debug(f"[RateLimiter] ZSET error: {e}")
            return

        # Esperamos un intervalo mínimo antes de reintentar
        remaining = deadline - time.monotonic()
        time.sleep(min(intervalo, remaining))

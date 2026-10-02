"""
Límite de pedidos por ventana deslizante, en memoria.

Protege lo que cuesta plata o abre puertas: las llamadas a la IA (se pagan por uso), los sync manuales, la importación de planillas, el
inicio de sesión con Mercado Libre y /admin. Cada regla cuenta los pedidos de una clave (el usuario de la sesión o, si no hay, la IP) en
una ventana de tiempo; pasado el máximo, el pedido recibe 429 con Retry-After.

Es por proceso: con N workers el límite efectivo es hasta N veces el configurado. Alcanza para frenar abuso y errores de cliente en bucle;
no pretende ser un contador exacto (para eso haría falta Redis).
"""
import threading
import time
from collections import deque

# (prefijos de ruta, métodos o None=todos, máximo, ventana en segundos, clave: "usuario" | "ip", nombre)
REGLAS = (
    (("/conectar", "/conectar_otra_cuenta", "/callback", "/reconectar"), None, 20, 60, "ip", "oauth"),
    (("/api/chat_ia", "/api/costos_chat", "/api/logros/coach", "/api/preguntas/sugerir", "/api/drawer/optimizar_titulo"), None, 20, 60, "usuario", "ia"),
    (("/sincronizar_todo", "/api/flex/sincronizar"), {"POST"}, 4, 60, "usuario", "sync"),
    (("/api/costos/importar",), {"POST"}, 10, 60, "usuario", "importar"),
    (("/api/reactivar", "/api/precios"), {"POST"}, 10, 60, "usuario", "cambios"),
    (("/api/feedback",), {"POST"}, 10, 60, "usuario", "feedback"),
    (("/cuenta/descargar_datos",), {"POST"}, 3, 60, "usuario", "descargar"),
    (("/admin",), None, 60, 60, "ip", "admin"),
)
GENERAL = (600, 60)       # por IP, para todo lo que no es estático, healthcheck ni webhook
EXENTAS = ("/static/", "/healthz", "/notificaciones_meli", "/webhook")

_lock = threading.Lock()
_registro = {}            # (regla, clave) -> deque de instantes
_ultima_limpieza = 0.0


def _limpiar(ahora):
    """Saca las claves que no se usaron en la última hora, para que el diccionario no crezca sin fin."""
    global _ultima_limpieza
    if ahora - _ultima_limpieza < 300:
        return
    _ultima_limpieza = ahora
    for k in [k for k, v in _registro.items() if not v or ahora - v[-1] > 3600]:
        _registro.pop(k, None)


def _contar(regla, clave, maximo, ventana, ahora):
    """Registra un pedido. Devuelve 0 si pasa o los segundos que faltan para que vuelva a pasar."""
    with _lock:
        _limpiar(ahora)
        q = _registro.setdefault((regla, clave), deque())
        while q and ahora - q[0] > ventana:
            q.popleft()
        if len(q) >= maximo:
            return max(1, int(ventana - (ahora - q[0])) + 1)
        q.append(ahora)
        return 0


def revisar(ruta, metodo, usuario_id, ip, ahora=None):
    """None si el pedido pasa; si no, los segundos de espera (para Retry-After)."""
    if ruta.startswith(EXENTAS):
        return None
    ahora = time.monotonic() if ahora is None else ahora
    ip = ip or "?"
    for prefijos, metodos, maximo, ventana, por, nombre in REGLAS:
        if (metodos is None or metodo in metodos) and any(ruta == p or ruta.startswith(p + "/") for p in prefijos):
            clave = f"u{usuario_id}" if por == "usuario" and usuario_id else f"ip{ip}"
            espera = _contar(nombre, clave, maximo, ventana, ahora)
            if espera:
                return espera
    return _contar("general", f"ip{ip}", GENERAL[0], GENERAL[1], ahora) or None


def reiniciar():
    with _lock:
        _registro.clear()

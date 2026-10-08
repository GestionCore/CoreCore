"""
Conexión a Postgres/Supabase — con psycopg 3 (no psycopg2). Se migró
porque psycopg2-binary todavía no tiene una versión compilada para
Python 3.14 (muy nuevo), y compilarlo desde cero en Windows requiere
pg_config, que no viene instalado ahí. psycopg3 resuelve esto con
wheels precompilados que sí cubren versiones nuevas de Python.

Cada conexión que se usa para atender un pedido de un usuario normal
DEBE pasar por `obtener_conexion_usuario`, que setea `app.usuario_actual`
— es lo que hace que las políticas de Row Level Security del esquema
realmente filtren por dueño.

Usa ConnectionPool de psycopg_pool (pensado para multi-hilo desde el
diseño, no como un extra) — Flask corre con threaded=True para atender
varios pedidos a la vez.

Para la tabla `meli_tokens` existe un canal completamente aparte
(`obtener_conexion_admin`), con un rol que tiene BYPASSRLS — la política
de esa tabla bloquea CUALQUIER operación (hasta el INSERT) desde el rol
normal a propósito, así que los tokens solo se tocan desde acá. Usalo
ÚNICAMENTE en token_manager.py — no lo importes en otro lado.
"""
from psycopg_pool import ConnectionPool
import atexit
import os
import threading
import config

# Tamaño máximo de cada pool POR PROCESO. El pooler de Supabase en modo sesión admite 15 conexiones por rol para TODO el proyecto, y
# cada worker de gunicorn de cada máquina tiene su propio pool: workers × máquinas × DB_POOL_MAX tiene que quedar en 12 o menos
# (fly.toml fija el valor de producción; con 2 máquinas × 2 workers, 3). Los scripts y el desarrollo local usan lo que sobra.
POOL_MAX = max(1, int(os.getenv("DB_POOL_MAX", "4")))
POOL_ADMIN_MAX = max(1, int(os.getenv("DB_POOL_ADMIN_MAX", "2")))
# Cuánto espera un pedido por una conexión libre antes de rendirse (psycopg_pool: 30 s por defecto). Con el pool chico que exige el tope de Supabase, esperar 30 s
# solo apila pedidos: es mejor fallar rápido y mostrar "mucha demanda" (503) que dejar a la persona colgada medio minuto.
POOL_TIMEOUT = max(1.0, float(os.getenv("DB_POOL_TIMEOUT", "10")))

_pool = None
_pool_admin = None

# La creación perezosa de los pools NECESITA lock: sin él, dos pedidos
# simultáneos al arrancar veían `_pool is None` a la vez y creaban dos
# pools. El primero quedaba huérfano con sus conexiones abiertas (contra el
# tope de 15 de Supabase) y, peor, un pedido sacaba la conexión de un pool y
# la devolvía a otro → ValueError "can't return connection to pool".
_lock_pools = threading.Lock()


def _obtener_pool():
    global _pool
    if _pool is None:
        with _lock_pools:
            if _pool is None:
                _pool = _crear_pool()
    return _pool


def _crear_pool():
    if not config.DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL en las variables de entorno.")
    # OJO — esto NO puede volver a subirse sin volver a hacer la cuenta
    # de abajo: cada proceso worker de gunicorn tiene su PROPIO pool
    # (esto es un global de módulo, psycopg_pool no se comparte entre
    # procesos), y estamos corriendo con 2 workers. El pooler de
    # Supabase en modo "Sesión" (el que hace falta para que RLS con
    # set_config(..., true) sea confiable — ver el comentario grande
    # más abajo) tiene un tope DURO de 15 conexiones total para todo
    # el proyecto, lo uses como lo uses. Con min_size=4/max_size=20
    # de antes, el peor caso era (20 + 10 del pool admin) × 2 workers
    # = 60 conexiones posibles — muy por encima de 15, y en producción
    # tiró exactamente el error que predice ese límite
    # (EMAXCONNSESSION / "couldn't get a connection after 30 sec"),
    # tumbando el scheduler y varias páginas de golpe.
    # Presupuesto actual: (4 + 2) × 2 workers = 12, más la conexión
    # fija que scheduler.py mantiene abierta para el advisory lock =
    # 13, dejando 2 de margen bajo el tope de 15.
    return ConnectionPool(config.DATABASE_URL, min_size=1, max_size=POOL_MAX, timeout=POOL_TIMEOUT, open=True)


def _obtener_pool_admin():
    global _pool_admin
    if _pool_admin is None:
        with _lock_pools:
            if _pool_admin is None:
                _pool_admin = _crear_pool_admin()
    return _pool_admin


def _crear_pool_admin():
    if not config.DATABASE_URL_ADMIN:
        raise RuntimeError("Falta DATABASE_URL_ADMIN en las variables de entorno.")
    # Mismo presupuesto de conexiones que _obtener_pool — ver ese
    # comentario. token_manager.asegurar_token_valido pasa por acá en
    # casi todas las rutas autenticadas, por eso conserva min_size=1
    # en vez de 0 (evita abrir una conexión nueva en el camino
    # caliente de cada pedido), pero max_size se recortó fuerte para
    # no volver a pisar el tope de 15 de Supabase.
    return ConnectionPool(config.DATABASE_URL_ADMIN, min_size=1, max_size=POOL_ADMIN_MAX, timeout=POOL_TIMEOUT, open=True)


@atexit.register
def _cerrar_pools_al_salir():
    """
    Sin esto, al cortar la app (Ctrl+C) Python mata los hilos internos
    del pool a la fuerza mientras se está apagando, y psycopg_pool tira
    un PythonFinalizationError inofensivo pero feo en la consola. Cerrar
    los pools de forma prolija ANTES de que el intérprete empiece a
    apagarse evita ese ruido.
    """
    if _pool is not None:
        _pool.close()
    if _pool_admin is not None:
        _pool_admin.close()


def obtener_conexion_usuario(usuario_id, cuenta_id=None):
    """
    Conexión para atender un pedido de un usuario autenticado — deja
    seteada la variable de sesión que las políticas de RLS usan para
    filtrar. Acordate de devolverla con `liberar_conexion` cuando termines
    (o usar el context manager `conexion_usuario` de más abajo).

    `cuenta_id` es opcional — es la defensa en profundidad para el
    aislamiento entre las VARIAS cuentas de un mismo usuario (plan
    Elite): además de `app.usuario_actual` (que ya filtra por dueño),
    setea `app.cuenta_actual`, que las políticas RLS de las tablas
    "hijas" (ventas, productos_padre, etc. — no `cuentas_meli`) usan
    para restringir también a la cuenta activa en sesión, no
    "cualquier cuenta de este usuario". Si no se pasa, queda en '' y
    las políticas no agregan esa restricción — o sea, mismo
    comportamiento que antes de este cambio (no rompe ningún call site
    que todavía no la pase). SIEMPRE se setea explícitamente (a '' si
    hace falta) para no arrastrar un valor viejo de una conexión
    reciclada del pool.
    """
    conexion = _obtener_pool().getconn()
    try:
        _dejar_lista_para_rls(conexion, usuario_id, cuenta_id)
    except BaseException:
        # La conexión ya salió del pool y nadie la va a tener: si no se devuelve acá se pierde para siempre, y con el pool de 3 bastan 3 fallas para dejar sin base a todo el worker.
        liberar_conexion(conexion)
        raise
    return conexion


def _dejar_lista_para_rls(conexion, usuario_id, cuenta_id):
    cursor = conexion.cursor()
    # set_config() en vez de "SET app.usuario_actual = %s": Postgres no
    # acepta parámetros del lado del servidor (los $1 que usa psycopg3
    # por default) dentro de una sentencia SET — sí los acepta en una
    # función común como set_config(), que hace exactamente lo mismo.
    #
    # is_local=true (no false): esto lo hace válido para TODA la
    # transacción actual en vez de "toda la sesión" — que es justo la
    # duración real de nuestro bloque `with conexion_usuario(...)`, ya
    # que psycopg3 no usa autocommit por default. Es más seguro con un
    # pooler como el de Supabase (que puede no preservar variables de
    # sesión entre instrucciones si está en modo "transaction"), y de
    # paso se limpia solo al hacer commit, sin arriesgar que quede un
    # valor viejo pegado si la misma conexión física se reutiliza
    # después para otro usuario.
    # Las dos variables en UNA sentencia: un viaje de ida y vuelta menos por cada bloque `with` (hay 5-7 por página).
    cursor.execute(
        "SELECT set_config('app.usuario_actual', %s, true), set_config('app.cuenta_actual', %s, true)",
        (str(usuario_id), str(cuenta_id) if cuenta_id is not None else ""),
    )
    cursor.close()


def liberar_conexion(conexion):
    _obtener_pool().putconn(conexion)


def obtener_conexion_admin():
    """Solo para token_manager.py — bypassea RLS. No usar en otro lado."""
    return _obtener_pool_admin().getconn()


def liberar_conexion_admin(conexion):
    _obtener_pool_admin().putconn(conexion)


class conexion_usuario:
    """
    Context manager: with conexion_usuario(usuario_id) as conn: ...
    Se encarga de pedir la conexión, dejarla lista para RLS, y devolverla
    al pool al salir — así ninguna ruta se olvida de liberarla.

    `cuenta_id` es opcional (ver `obtener_conexion_usuario`) — pasalo
    siempre que lo tengas a mano (típicamente `g.cuenta_id` en una
    ruta de Flask) para que RLS también aísle entre las cuentas del
    mismo usuario, no solo entre usuarios distintos.
    """
    def __init__(self, usuario_id, cuenta_id=None):
        self.usuario_id = usuario_id
        self.cuenta_id = cuenta_id
        self.conexion = None

    def __enter__(self):
        self.conexion = obtener_conexion_usuario(self.usuario_id, self.cuenta_id)
        return self.conexion

    def __exit__(self, exc_type, exc_val, exc_tb):
        # `finally`: si el commit falla (corte de red, transacción abortada) o el rollback no puede, la conexión IGUAL vuelve al pool. Antes se perdía: el pool es de 3 por worker.
        try:
            if exc_type is None:
                self.conexion.commit()
            else:
                self.conexion.rollback()
        finally:
            liberar_conexion(self.conexion)


class conexion_admin:
    """Igual que conexion_usuario, pero para el canal admin de tokens."""
    def __init__(self):
        self.conexion = None

    def __enter__(self):
        self.conexion = obtener_conexion_admin()
        return self.conexion

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:                                      # igual que conexion_usuario: la conexión vuelve al pool pase lo que pase con el commit o el rollback
            if exc_type is None:
                self.conexion.commit()
            else:
                self.conexion.rollback()
        finally:
            liberar_conexion_admin(self.conexion)

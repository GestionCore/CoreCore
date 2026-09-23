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
import psycopg
from psycopg_pool import ConnectionPool
import atexit
import config

_pool = None
_pool_admin = None


def _obtener_pool():
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError("Falta DATABASE_URL en las variables de entorno.")
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=20, open=True)
    return _pool


def _obtener_pool_admin():
    global _pool_admin
    if _pool_admin is None:
        if not config.DATABASE_URL_ADMIN:
            raise RuntimeError("Falta DATABASE_URL_ADMIN en las variables de entorno.")
        _pool_admin = ConnectionPool(config.DATABASE_URL_ADMIN, min_size=1, max_size=10, open=True)
    return _pool_admin


@atexit.register
def _cerrar_pools_al_salir():
    """
    Sin esto, al cortar la app (Ctrl+C) Python mata los hilos internos
    del pool a la fuerza mientras se está apagando, y psycopg_pool tira
    un PythonFinalizationError inofensivo pero feo en la consola. Cerrar
    los pools de forma prolija ANTES de que el intérprete empiece a
    apagarse evita ese ruido.
    """
    global _pool, _pool_admin
    if _pool is not None:
        _pool.close()
    if _pool_admin is not None:
        _pool_admin.close()


def obtener_conexion_usuario(usuario_id):
    """
    Conexión para atender un pedido de un usuario autenticado — deja
    seteada la variable de sesión que las políticas de RLS usan para
    filtrar. Acordate de devolverla con `liberar_conexion` cuando termines
    (o usar el context manager `conexion_usuario` de más abajo).
    """
    conexion = _obtener_pool().getconn()
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
    cursor.execute("SELECT set_config('app.usuario_actual', %s, true)", (str(usuario_id),))
    cursor.close()
    return conexion


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
    """
    def __init__(self, usuario_id):
        self.usuario_id = usuario_id
        self.conexion = None

    def __enter__(self):
        self.conexion = obtener_conexion_usuario(self.usuario_id)
        return self.conexion

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conexion.commit()
        else:
            self.conexion.rollback()
        liberar_conexion(self.conexion)


class conexion_admin:
    """Igual que conexion_usuario, pero para el canal admin de tokens."""
    def __init__(self):
        self.conexion = None

    def __enter__(self):
        self.conexion = obtener_conexion_admin()
        return self.conexion

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conexion.commit()
        else:
            self.conexion.rollback()
        liberar_conexion_admin(self.conexion)

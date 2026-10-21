import os
import sys

# Las pruebas se corren desde la raíz del proyecto: los módulos (utils, precios, cobros…) viven ahí.
os.environ.setdefault("CORELUX_PRUEBAS", "1")     # antes de importar config: sin .env (CI) no aborta por variables faltantes

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# El .env se carga ANTES de recolectar las pruebas: los módulos *_db.py deciden si se omiten mirando DATABASE_URL al importarse, y
# config.py (que carga el .env) todavía no se importó para el primero de ellos. En una terminal sin la variable exportada se salteaba
# justo test_aislamiento_db (las 16 pruebas de RLS) y la corrida igual daba verde.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(RAIZ, ".env"))
except ImportError:
    pass


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_usuario_pegado_en_sentry():
    """`login_requerido` informa el usuario a Sentry. En producción cada pedido tiene su propio contexto; en las pruebas todas comparten el proceso, así que lo que una puso se ve en la siguiente."""
    yield
    try:
        import sentry_sdk
        sentry_sdk.get_isolation_scope().clear()
        sentry_sdk.get_current_scope().clear()
    except Exception:
        pass


class _TransaccionFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _ConexionFalsa:
    """Lo mínimo de una conexión que usa el código con puntos de guardado (`cursor.connection.transaction()`)."""
    def transaction(self):
        return _TransaccionFalsa()


class CursorFalso:
    """Cursor de mentira para probar funciones que arman datos a partir de consultas: devuelve, en orden, los resultados que se le cargan."""

    connection = _ConexionFalsa()

    def __init__(self, *resultados):
        self.resultados = list(resultados)
        self.consultas = []
        self._actual = []

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        self._actual = self.resultados.pop(0) if self.resultados else []

    def fetchall(self):
        return self._actual

    def fetchone(self):
        return self._actual[0] if self._actual else None

"""
Refresco del token de Mercado Libre. El refresh_token es de UN SOLO USO: si dos pedidos ven el access_token vencido a la vez y los dos refrescan, el segundo gasta un refresh_token ya
usado, MeLi contesta `invalid_grant` y la cuenta se marcaba como desconectada sin estarlo. Se prueba con una base simulada (sin red ni Postgres) y con hilos de verdad.
"""
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import crypto_utils
import db
from auth import oauth_meli
from auth import token_manager as tm


class BaseSimulada:
    """meli_tokens y cuentas_meli de UNA cuenta. `conexion_admin()` abre una transacción que se confirma al salir bien y se deshace si hay una excepción."""

    def __init__(self, vencido=True):
        ahora = datetime.now(timezone.utc)
        self.fila = ("acceso-viejo", "refresco-1", ahora - timedelta(minutes=1) if vencido else ahora + timedelta(hours=5))
        self.cuenta_activa = True
        self.refresco_vigente = "refresco-1"
        self.numero = 1
        self.refrescos_pedidos = 0
        self.invalid_grants = 0
        self.consultas = []
        self.commits = 0
        self.rollbacks = 0
        self.candado_postgres = threading.Lock()         # el advisory lock: lo toma quien ejecuta pg_advisory_xact_lock y se suelta al terminar su transacción
        self.guarda = threading.Lock()

    def refrescar(self, refresh_token):
        """oauth_meli.refrescar_token: el refresh_token solo sirve UNA vez."""
        time.sleep(0.03)                                  # la llamada a MeLi tarda: ahí es donde se pisan los pedidos
        with self.guarda:
            self.refrescos_pedidos += 1
            if refresh_token != self.refresco_vigente:
                self.invalid_grants += 1
                return False, "MeLi rechazó el refresh: 400 - invalid_grant"
            self.numero += 1
            self.refresco_vigente = f"refresco-{self.numero}"
            return True, {"access_token": f"acceso-{self.numero}", "refresh_token": self.refresco_vigente, "expires_in": 21600}

    @contextmanager
    def conexion_admin(self):
        base = self
        estado = {"tiene_candado": False, "antes": (base.fila, base.cuenta_activa)}

        class Cursor:
            def __init__(self):
                self.resultado = None

            def execute(self, sql, params=None):
                sql_normal = " ".join(sql.split())
                base.consultas.append(sql_normal)
                if "pg_advisory_xact_lock" in sql_normal:
                    base.candado_postgres.acquire()
                    estado["tiene_candado"] = True
                elif sql_normal.startswith("SELECT access_token_cifrado"):
                    with base.guarda:
                        self.resultado = base.fila
                elif sql_normal.startswith("INSERT INTO meli_tokens"):
                    with base.guarda:
                        base.fila = (params[1], params[2], params[3])
                elif sql_normal.startswith("DELETE FROM meli_tokens"):
                    with base.guarda:
                        base.fila = None
                elif sql_normal.startswith("UPDATE cuentas_meli SET activa = false"):
                    with base.guarda:
                        base.cuenta_activa = False

            def fetchone(self):
                return self.resultado

        class Conexion:
            def cursor(self):
                return Cursor()

        try:
            yield Conexion()
            base.commits += 1
        except BaseException:
            with base.guarda:
                base.fila, base.cuenta_activa = estado["antes"]
            base.rollbacks += 1
            raise
        finally:
            if estado["tiene_candado"]:
                base.candado_postgres.release()


@pytest.fixture
def base(monkeypatch):
    b = BaseSimulada()
    monkeypatch.setattr(db, "conexion_admin", b.conexion_admin)
    monkeypatch.setattr(oauth_meli, "refrescar_token", b.refrescar)
    monkeypatch.setattr(crypto_utils, "cifrar", lambda x: x)
    monkeypatch.setattr(crypto_utils, "descifrar", lambda x: x)
    monkeypatch.setattr(tm, "_candados_locales", {})
    return b


def _en_paralelo(n, funcion):
    """Lanza `n` hilos a la vez (arrancan juntos) y devuelve [(resultado, error)]."""
    salidas, barrera = [None] * n, threading.Barrier(n)

    def corre(i):
        barrera.wait()
        try:
            salidas[i] = (funcion(), None)
        except Exception as e:
            salidas[i] = (None, e)

    hilos = [threading.Thread(target=corre, args=(i,)) for i in range(n)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    return salidas


def test_con_el_token_vigente_no_se_refresca_ni_se_toma_ningun_candado(base):
    base.fila = ("acceso-bueno", "refresco-1", datetime.now(timezone.utc) + timedelta(hours=5))
    assert tm.asegurar_token_valido(1) == "acceso-bueno"
    assert base.refrescos_pedidos == 0 and not any("pg_advisory_xact_lock" in c for c in base.consultas)


def test_con_el_token_vencido_se_toma_el_advisory_lock_de_la_cuenta_y_se_guarda_el_refresh_nuevo(base):
    assert tm.asegurar_token_valido(7) == "acceso-2"
    bloqueo = [c for c in base.consultas if "pg_advisory_xact_lock" in c]
    assert len(bloqueo) == 1 and base.fila[1] == "refresco-2" and base.refresco_vigente == "refresco-2"
    assert any("lock_timeout" in c for c in base.consultas)                          # el lock no espera para siempre


def test_muchos_pedidos_a_la_vez_gastan_un_solo_refresh_y_nadie_desconecta_la_cuenta(base):
    salidas = _en_paralelo(12, lambda: tm.asegurar_token_valido(1))
    assert [e for _, e in salidas] == [None] * 12
    assert {t for t, _ in salidas} == {"acceso-2"}
    assert base.refrescos_pedidos == 1 and base.invalid_grants == 0 and base.cuenta_activa and base.fila is not None


def test_entre_procesos_alcanza_con_el_advisory_lock_aunque_no_haya_candado_local(base, monkeypatch):
    """Dos procesos (dos máquinas) no comparten el candado de hilos: lo único que los frena es el lock de Postgres."""
    class SinCandado:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tm, "_candado_local", lambda cuenta_id: SinCandado())
    salidas = _en_paralelo(10, lambda: tm.asegurar_token_valido(1))
    assert [e for _, e in salidas] == [None] * 10 and {t for t, _ in salidas} == {"acceso-2"}
    assert base.refrescos_pedidos == 1 and base.invalid_grants == 0 and base.cuenta_activa


def test_control_sin_ninguna_proteccion_el_segundo_refresh_da_invalid_grant_y_desconecta_la_cuenta(base, monkeypatch):
    """Lo que pasaba antes: sin candados la carrera es real. Si esta prueba deja de fallar así, el resto ya no prueba nada."""
    class SinCandado:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class SinLock(BaseSimulada):
        pass

    monkeypatch.setattr(tm, "_candado_local", lambda cuenta_id: SinCandado())
    original = base.conexion_admin

    @contextmanager
    def sin_advisory():
        with original() as conexion:
            cursor_original = conexion.cursor

            class CursorSinLock:
                def __init__(self):
                    self.c = cursor_original()

                def execute(self, sql, params=None):
                    if "pg_advisory_xact_lock" in sql or "lock_timeout" in sql:
                        return
                    self.c.execute(sql, params)

                def fetchone(self):
                    return self.c.fetchone()

            class ConexionSinLock:
                def cursor(self):
                    return CursorSinLock()

            yield ConexionSinLock()

    monkeypatch.setattr(db, "conexion_admin", sin_advisory)
    _en_paralelo(8, lambda: tm.asegurar_token_valido(1))
    assert base.refrescos_pedidos > 1 and base.invalid_grants >= 1                   # varios gastaron el mismo refresh_token


def test_invalid_grant_confirma_la_desconexion_aunque_despues_se_levante_el_aviso(base):
    """El borrado de tokens y la baja de la cuenta se guardan (commit): levantar el error DENTRO de la transacción los habría deshecho."""
    base.refresco_vigente = "otro"                                                   # MeLi ya no reconoce el refresh_token guardado: la cuenta quedó revocada de verdad
    with pytest.raises(tm.CuentaDesconectada):
        tm.asegurar_token_valido(1)
    assert base.fila is None and base.cuenta_activa is False and base.rollbacks == 0 and base.commits >= 1


def test_un_error_pasajero_de_mercado_libre_no_desconecta_la_cuenta(base, monkeypatch):
    monkeypatch.setattr(oauth_meli, "refrescar_token", lambda r: (False, "Error de conexión refrescando el token: timeout"))
    with pytest.raises(RuntimeError):
        tm.asegurar_token_valido(1)
    assert base.cuenta_activa is True and base.fila is not None


def test_sin_tokens_guardados_la_cuenta_esta_desconectada(base):
    base.fila = None
    with pytest.raises(tm.CuentaDesconectada):
        tm.asegurar_token_valido(1)


# ── 401: se fuerza un refresh real, pero no si otro ya lo cambió ─────────────────────────────────────────────────────────────────────────────
def test_un_401_con_el_token_vigente_fuerza_un_refresh_real(base):
    base.fila = ("acceso-viejo", "refresco-1", datetime.now(timezone.utc) + timedelta(hours=5))
    assert tm.refrescar_token_rechazado(1, "acceso-viejo") == "acceso-2"
    assert base.refrescos_pedidos == 1


def test_un_401_con_un_token_que_otro_ya_cambio_usa_el_nuevo_sin_refrescar_de_nuevo(base):
    base.fila = ("acceso-nuevo", "refresco-2", datetime.now(timezone.utc) + timedelta(hours=5))
    assert tm.refrescar_token_rechazado(1, "acceso-viejo") == "acceso-nuevo"
    assert base.refrescos_pedidos == 0


def test_varios_401_a_la_vez_gastan_un_solo_refresh(base):
    base.fila = ("acceso-viejo", "refresco-1", datetime.now(timezone.utc) + timedelta(hours=5))
    salidas = _en_paralelo(8, lambda: tm.refrescar_token_rechazado(1, "acceso-viejo"))
    assert [e for _, e in salidas] == [None] * 8 and {t for t, _ in salidas} == {"acceso-2"}
    assert base.refrescos_pedidos == 1 and base.invalid_grants == 0 and base.cuenta_activa


# ── timeout ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Respuesta:
    def __init__(self, codigo):
        self.status_code = codigo


def test_llamar_api_meli_usa_un_timeout_por_defecto_y_respeta_el_que_se_le_pase(base, monkeypatch):
    base.fila = ("acceso-bueno", "refresco-1", datetime.now(timezone.utc) + timedelta(hours=5))
    vistos = []
    monkeypatch.setattr(tm.requests, "request", lambda metodo, url, **kw: vistos.append(kw) or _Respuesta(200))
    tm.llamar_api_meli(1, "GET", "https://x")
    tm.llamar_api_meli(1, "GET", "https://x", timeout=3)
    assert vistos[0]["timeout"] == tm.TIMEOUT_POR_DEFECTO == 15 and vistos[1]["timeout"] == 3


def test_llamar_api_meli_reintenta_una_vez_con_el_token_nuevo_si_recibe_401(base, monkeypatch):
    base.fila = ("acceso-viejo", "refresco-1", datetime.now(timezone.utc) + timedelta(hours=5))
    usados = []

    def pedir(metodo, url, headers=None, **kw):
        usados.append(headers["Authorization"])
        return _Respuesta(401 if len(usados) == 1 else 200)

    monkeypatch.setattr(tm.requests, "request", pedir)
    assert tm.llamar_api_meli(1, "GET", "https://x").status_code == 200
    assert usados == ["Bearer acceso-viejo", "Bearer acceso-2"]

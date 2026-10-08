"""/healthz/db no puede comerse el pool con una lluvia de pedidos, y una conexión del pool vuelve siempre aunque el commit o el rollback fallen."""
import pytest
from psycopg import OperationalError

import db
import seguridad


# ── /healthz/db con caché ────────────────────────────────────────────────────────────────────────────────────────────────────

class _ConexionContada:
    def __init__(self, contador, falla):
        self.contador, self.falla = contador, falla

    def __enter__(self):
        self.contador.append(1)
        if self.falla:
            raise OperationalError("la base no responde")
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self

    def execute(self, sql):
        return None


@pytest.fixture
def cliente_healthz(monkeypatch):
    import app as modulo_app
    seguridad._estado_healthz_db.update(ok=None, vence=0.0)
    yield modulo_app.app.test_client()
    seguridad._estado_healthz_db.update(ok=None, vence=0.0)


def test_una_lluvia_de_pedidos_a_healthz_db_hace_una_sola_consulta(monkeypatch, cliente_healthz):
    consultas = []
    monkeypatch.setattr(db, "conexion_admin", lambda: _ConexionContada(consultas, falla=False))
    for _ in range(40):
        r = cliente_healthz.get("/healthz/db")
        assert r.status_code == 200 and r.get_json()["db"] is True
    assert len(consultas) == 1
    seguridad._estado_healthz_db["vence"] = 0.0                      # pasó la ventana: vuelve a consultar una vez
    cliente_healthz.get("/healthz/db")
    assert len(consultas) == 2


def test_con_la_base_caida_tampoco_se_consulta_en_cada_pedido_y_se_recupera(monkeypatch, cliente_healthz):
    consultas = []
    monkeypatch.setattr(db, "conexion_admin", lambda: _ConexionContada(consultas, falla=True))
    for _ in range(15):
        assert cliente_healthz.get("/healthz/db").status_code == 503
    assert len(consultas) == 1                                       # cada intento fallido puede esperar hasta el timeout del pool: no uno por visitante
    assert seguridad.SEGUNDOS_CACHE_HEALTHZ_DB_CAIDA < seguridad.SEGUNDOS_CACHE_HEALTHZ_DB      # una caída se vuelve a mirar antes que una base sana
    monkeypatch.setattr(db, "conexion_admin", lambda: _ConexionContada(consultas, falla=False))
    seguridad._estado_healthz_db["vence"] = 0.0
    assert cliente_healthz.get("/healthz/db").status_code == 200


def test_healthz_liviano_no_toca_la_base(monkeypatch, cliente_healthz):
    monkeypatch.setattr(db, "conexion_admin", lambda: pytest.fail("/healthz no debe usar la base"))
    assert cliente_healthz.get("/healthz").status_code == 200


# ── Las conexiones vuelven al pool pase lo que pase ──────────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, conexion):
        self.conexion = conexion

    def execute(self, sql, params=None):
        if self.conexion.falla_execute:
            raise OperationalError("se cortó la conexión")

    def close(self):
        pass


class _Conexion:
    def __init__(self, falla_commit=False, falla_rollback=False, falla_execute=False):
        self.falla_commit, self.falla_rollback, self.falla_execute = falla_commit, falla_rollback, falla_execute

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        if self.falla_commit:
            raise OperationalError("no se pudo confirmar")

    def rollback(self):
        if self.falla_rollback:
            raise OperationalError("no se pudo deshacer")


class _Pool:
    def __init__(self, conexion):
        self.conexion, self.devueltas = conexion, []

    def getconn(self):
        return self.conexion

    def putconn(self, conexion):
        self.devueltas.append(conexion)


@pytest.fixture(params=["usuario", "admin"])
def canal(request, monkeypatch):
    """Cada prueba corre para los dos canales de conexión: devuelve (abrir, pool_falso)."""
    def preparar(conexion):
        pool = _Pool(conexion)
        monkeypatch.setattr(db, "_obtener_pool", lambda: pool)
        monkeypatch.setattr(db, "_obtener_pool_admin", lambda: pool)
        return (lambda: db.conexion_usuario(1, 2)) if request.param == "usuario" else (lambda: db.conexion_admin()), pool
    return preparar


def test_si_el_commit_falla_la_conexion_vuelve_al_pool(canal):
    conexion = _Conexion(falla_commit=True)
    abrir, pool = canal(conexion)
    with pytest.raises(OperationalError):
        with abrir():
            pass
    assert pool.devueltas == [conexion]


def test_si_el_rollback_falla_la_conexion_vuelve_al_pool_y_se_ve_el_error_original(canal):
    conexion = _Conexion(falla_rollback=True)
    abrir, pool = canal(conexion)
    with pytest.raises(Exception):
        with abrir():
            raise ValueError("falló la consulta")
    assert pool.devueltas == [conexion]


def test_si_el_cuerpo_falla_se_hace_rollback_y_la_conexion_vuelve(canal):
    conexion = _Conexion()
    abrir, pool = canal(conexion)
    with pytest.raises(ValueError):
        with abrir():
            raise ValueError("boom")
    assert pool.devueltas == [conexion]


def test_si_no_se_puede_dejar_lista_la_conexion_para_rls_vuelve_al_pool(monkeypatch):
    conexion = _Conexion(falla_execute=True)
    pool = _Pool(conexion)
    monkeypatch.setattr(db, "_obtener_pool", lambda: pool)
    with pytest.raises(OperationalError):
        with db.conexion_usuario(1, 2):
            pytest.fail("no debería llegar al cuerpo")
    assert pool.devueltas == [conexion]               # antes quedaba perdida: con un pool de 3, tres fallas dejaban al worker sin base


def test_el_camino_normal_hace_commit_y_devuelve_la_conexion(canal):
    conexion = _Conexion()
    abrir, pool = canal(conexion)
    with abrir():
        pass
    assert pool.devueltas == [conexion]

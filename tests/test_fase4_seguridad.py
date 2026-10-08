"""
Fase 4 (backend y seguridad). 24 y 25 ya estaban resueltos y con pruebas (tests/test_correcciones_auditoria.py). Acá: 23 (zona horaria real), 26 (webhook: qué se registra) y 27
(el `state` de OAuth). Sobre el 27: el flujo de «conectar otra cuenta» valida el state contra la BASE a propósito (el enlace se abre en OTRO navegador, migración 0013), así que exigir
la cookie ahí rompería esa función; el login normal SÍ la exige. Lo que se endureció: comparación en tiempo constante, un solo uso también en el mismo navegador, y rechazo del enlace
de otra persona abierto en un navegador con otra sesión de CoreLux (el CSRF clásico de OAuth).
"""
import importlib.util
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import utils
from auth import oauth_meli

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── 23. Zona horaria ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_argentina_usa_la_zona_real_y_hoy_da_menos_tres_horas():
    from zoneinfo import ZoneInfo
    assert isinstance(utils.ARGENTINA, ZoneInfo)
    assert utils.ARGENTINA.utcoffset(datetime(2026, 10, 7, 12, 0)) == timedelta(hours=-3)
    assert utils.ARGENTINA.utcoffset(datetime(2026, 1, 15, 12, 0)) == timedelta(hours=-3)             # no hay horario de verano
    assert datetime(2026, 10, 7, 2, 30, tzinfo=timezone.utc).astimezone(utils.ARGENTINA).day == 6        # 23:30 del día anterior
    assert utils.hoy_argentina() == datetime.now(utils.ARGENTINA).date()


def test_sin_base_de_zonas_horarias_cae_a_menos_tres_fijo(monkeypatch):
    import zoneinfo

    def sin_base(*a, **k):
        raise zoneinfo.ZoneInfoNotFoundError("sin tzdata")
    monkeypatch.setattr(zoneinfo, "ZoneInfo", sin_base)
    spec = importlib.util.spec_from_file_location("utils_sin_tzdata", os.path.join(RAIZ, "utils.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.ARGENTINA == timezone(timedelta(hours=-3))
    assert datetime(2026, 10, 7, 2, 30, tzinfo=timezone.utc).astimezone(modulo.ARGENTINA).day == 6


def test_la_base_de_zonas_horarias_esta_declarada_para_windows():
    assert "tzdata" in _leer("requirements.txt")


# ── 27. El state de OAuth ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_state_se_compara_en_tiempo_constante_y_dos_vacios_no_coinciden():
    assert oauth_meli.states_coinciden("abc123", "abc123") is True
    assert oauth_meli.states_coinciden("abc123", "abc124") is False
    for a, b in ((None, None), ("", ""), ("x", None), (None, "x"), ("", "x")):
        assert oauth_meli.states_coinciden(a, b) is False
    assert "hmac.compare_digest" in _leer("auth", "oauth_meli.py")


class _BaseFalsa:
    """conexion_admin de mentira: `pendientes` = {state: usuario_id} de las vinculaciones guardadas en la base."""

    def __init__(self, pendientes):
        self.pendientes, self.sentencias = dict(pendientes), []

    @contextmanager
    def conexion_admin(self):
        base = self

        class Cursor:
            def __init__(self):
                self.fila = None

            def execute(c, sql, params=None):
                texto = " ".join(sql.split())
                base.sentencias.append((texto, params))
                if texto.startswith("DELETE FROM oauth_vinculaciones_pendientes WHERE state = %s AND creado_en") and params[0] in base.pendientes:
                    c.fila = (base.pendientes.pop(params[0]),)
                else:
                    c.fila = None

            def fetchone(c):
                return c.fila

        class Conexion:
            def cursor(c):
                return Cursor()
        yield Conexion()


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


@pytest.fixture
def callback(monkeypatch):
    import app as aplicacion
    intercambios = []
    monkeypatch.setattr(aplicacion.oauth_meli, "intercambiar_codigo_por_token", lambda code: intercambios.append(code) or (False, "no se prueba el intercambio"))

    def preparar(pendientes=None, cookie_state=None, usuario_en_sesion=None):
        base = _BaseFalsa(pendientes or {})
        monkeypatch.setattr(aplicacion.db, "conexion_admin", base.conexion_admin)
        cliente = aplicacion.app.test_client()
        with cliente.session_transaction() as s:
            if cookie_state:
                s["oauth_state"] = cookie_state
            if usuario_en_sesion:
                s["usuario_id"] = usuario_en_sesion
        return cliente, base, intercambios
    return preparar


def _pedir(cliente, state="S1", code="C1"):
    r = cliente.get(f"/callback?code={code}&state={state}")
    return r.status_code, r.get_data(as_text=True)


def test_sin_cookie_ni_vinculacion_en_la_base_el_callback_no_intercambia_nada(callback):
    cliente, base, intercambios = callback()
    estado, html = _pedir(cliente)
    assert estado == 200 and "venció" in html and intercambios == []


def test_con_un_state_distinto_al_de_la_cookie_tampoco(callback):
    cliente, base, intercambios = callback(cookie_state="OTRO")
    estado, html = _pedir(cliente, state="S1")
    assert "venció" in html and intercambios == []


def test_si_el_state_coincide_con_la_cookie_se_acepta_y_se_gasta_el_de_la_base(callback):
    cliente, base, intercambios = callback(cookie_state="S1")
    _pedir(cliente, state="S1")
    assert intercambios == ["C1"]                                                                              # pasó la validación: llegó al intercambio del código
    assert any(s[0] == "DELETE FROM oauth_vinculaciones_pendientes WHERE state = %s" and s[1] == ("S1",) for s in base.sentencias)


def test_el_enlace_de_otra_persona_abierto_con_otra_sesion_de_corelux_se_rechaza(callback):
    """El CSRF de OAuth: alguien (usuario 7) arma su enlace y se lo hace abrir a una persona (usuario 9) que tiene su propia sesión de CoreLux."""
    cliente, base, intercambios = callback(pendientes={"S1": 7}, usuario_en_sesion=9)
    estado, html = _pedir(cliente)
    assert estado == 200 and "otra persona de CoreLux" in html and intercambios == []
    assert "S1" not in base.pendientes                                                                         # el enlace se gastó: hay que pedir otro


def test_el_enlace_propio_abierto_en_otro_navegador_sin_sesion_sigue_funcionando(callback):
    cliente, base, intercambios = callback(pendientes={"S1": 7})
    _pedir(cliente)
    assert intercambios == ["C1"]                                                                              # es la función de la migración 0013: completar el login de MeLi en otro navegador


def test_el_enlace_propio_con_la_misma_sesion_tambien_funciona(callback):
    cliente, base, intercambios = callback(pendientes={"S1": 7}, usuario_en_sesion=7)
    _pedir(cliente)
    assert intercambios == ["C1"]


def test_un_enlace_se_usa_una_sola_vez(callback):
    cliente, base, intercambios = callback(pendientes={"S1": 7})
    _pedir(cliente)
    _pedir(cliente)
    assert intercambios == ["C1"]                                                                              # el segundo intento ya no encuentra el state


# ── 26. Webhook ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def webhook(monkeypatch):
    import app as aplicacion
    llamadas = []
    monkeypatch.setattr(aplicacion, "_en_segundo_plano", lambda funcion, *a: llamadas.append(a))
    monkeypatch.setattr(aplicacion.config, "MELI_CLIENT_ID", "5503910054141466")
    return aplicacion.app.test_client(), llamadas


def test_el_webhook_registra_si_la_notificacion_trae_application_id_propio_ajeno_o_ninguno(webhook, capsys):
    cliente, llamadas = webhook
    base = {"topic": "orders_v2", "resource": "/orders/1", "user_id": 5}
    for extra, esperado in (({"application_id": 5503910054141466}, "propia"), ({"application_id": "5503910054141466"}, "propia"), ({"application_id": 1}, "ajena"), ({}, "ausente")):
        cliente.post("/notificaciones_meli", json=dict(base, **extra))
        assert f"[Webhook] tema=orders_v2 application_id={esperado}" in capsys.readouterr().out
    assert len(llamadas) == 2                                                                                  # solo las dos propias procesan: la ajena y la que no trae application_id se ignoran


def test_una_notificacion_sin_application_id_se_ignora_con_200_y_lo_dice_en_el_log(webhook, capsys):
    cliente, llamadas = webhook
    r = cliente.post("/notificaciones_meli", json={"topic": "orders_v2", "resource": "/orders/1", "user_id": 5})
    assert r.status_code == 200 and llamadas == []                                                             # 200 igual: MeLi deja de mandar si fallamos seguido
    assert "ignorada: no trae application_id" in capsys.readouterr().out


def test_sin_cliente_de_meli_configurado_no_se_puede_validar_y_no_se_descarta_nada(webhook, monkeypatch):
    cliente, llamadas = webhook
    monkeypatch.setattr("config.MELI_CLIENT_ID", "")
    r = cliente.post("/notificaciones_meli", json={"topic": "orders_v2", "resource": "/orders/1", "user_id": 5})
    assert r.status_code == 200 and len(llamadas) == 1                                                         # sin MELI_CLIENT_ID no hay contra qué comparar

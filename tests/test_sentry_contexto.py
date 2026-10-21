"""
Sentry sabe de quién es cada error: el usuario y la cuenta se informan desde login_requerido (antes un gancho before_request leía g.usuario_id, que todavía no existía en ese momento,
así que ningún evento llevaba a nadie), y cada error lleva la versión desplegada. Sentry se simula.
"""
import sentry_sdk

import app as modulo_app
from auth import middleware
from utils import hoy_argentina


def test_login_requerido_informa_el_usuario_y_la_cuenta_a_sentry(monkeypatch):
    capturado = {}
    monkeypatch.setattr(sentry_sdk, "set_user", lambda datos: capturado.update(usuario=datos))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda clave, valor: capturado.update({clave: valor}))
    hoy = hoy_argentina().strftime("%Y-%m-%d")

    @middleware.login_requerido
    def vista():
        return "ok"
    with modulo_app.app.test_request_context("/logout"):             # «logout» no necesita la base: el decorador llega hasta el final
        from flask import session
        session.update(usuario_id=3, cuenta_id=7, racha_actualizada_el=hoy, mas_usado_actualizado_el=hoy)
        assert vista() == "ok"
    assert capturado == {"usuario": {"id": "3"}, "cuenta_id": "7"}


def test_si_sentry_falla_el_pedido_sigue(monkeypatch):
    def _roto(*a, **k):
        raise RuntimeError("sentry caído")
    monkeypatch.setattr(sentry_sdk, "set_user", _roto)
    middleware._avisar_a_sentry(1, 2)                                 # no levanta


def test_ya_no_queda_el_gancho_que_nunca_veia_al_usuario():
    fuente = open(modulo_app.__file__, encoding="utf-8").read()
    assert "_sentry_set_user" not in fuente and 'release=os.getenv("CORELUX_VERSION")' in fuente

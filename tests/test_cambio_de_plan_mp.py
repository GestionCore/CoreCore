"""Cambiar de plan NO crea una segunda suscripción (se cobraría dos veces): se cambia el monto de la que ya tiene. Y las cuentas de cortesía nunca entran en un cobro."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import auditoria
import config
import pagos

MP_ID = "6e27f74e29fb44abbfa583901801f3e3"


# ── La decisión ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plan_actual, mp_id, pedido, esperado", [
    ("base", MP_ID, "elite", "cambiar"),
    ("base", MP_ID, "base", "mismo"),
    ("elite", MP_ID, "elite", "mismo"),
    ("elite", MP_ID, "base", "bajar_no_disponible"),
    ("elite", None, "base", "a_mano"),          # cuenta de cortesía: Elite gratis a mano, sin suscripción de Mercado Pago
    ("elite", None, "elite", "a_mano"),
    ("trial", None, "base", "nueva"),
    ("cancelado", MP_ID, "elite", "nueva"),
    (None, None, "base", "nueva"),
])
def test_que_hacer_cuando_alguien_toca_un_plan(plan_actual, mp_id, pedido, esperado):
    assert pagos.decidir_alta_o_cambio(plan_actual, mp_id, pedido) == esperado


# ── El pedido a Mercado Pago ──────────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, codigo):
        self.status_code = codigo


def _info(monto, referencia):
    return {"status": "authorized", "external_reference": referencia, "auto_recurring": {"transaction_amount": monto}}


def test_cambiar_el_plan_modifica_monto_nombre_y_referencia_de_la_misma_suscripcion(monkeypatch):
    enviados = []
    monkeypatch.setattr(pagos.requests, "put", lambda url, json=None, headers=None, timeout=None: enviados.append((url, json)) or _Resp(200))
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: _info(99000.0, "elite|77"))
    assert pagos.cambiar_plan_suscripcion(MP_ID, "elite", 77) is True
    url, cuerpo = enviados[0]
    assert url.endswith(f"/preapproval/{MP_ID}")
    assert cuerpo["auto_recurring"] == {"transaction_amount": 99000, "currency_id": "ARS"}
    assert cuerpo["external_reference"] == "elite|77" and "Elite" in cuerpo["reason"]


def test_si_mercado_pago_rechaza_el_cambio_no_se_da_por_hecho(monkeypatch):
    monkeypatch.setattr(pagos.requests, "put", lambda *a, **k: _Resp(400))
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: pytest.fail("no hay nada que verificar si MP rechazó el cambio"))
    assert pagos.cambiar_plan_suscripcion(MP_ID, "elite", 77) is False


def test_si_la_lectura_posterior_no_muestra_el_cambio_tampoco(monkeypatch):
    monkeypatch.setattr(pagos.requests, "put", lambda *a, **k: _Resp(200))
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: _info(40000.0, "base|77"))           # el monto no cambió
    assert pagos.cambiar_plan_suscripcion(MP_ID, "elite", 77) is False
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: _info(99000.0, "base|77"))           # cambió el monto pero quedó la referencia vieja: el webhook lo devolvería a Base
    assert pagos.cambiar_plan_suscripcion(MP_ID, "elite", 77) is False
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: None)
    assert pagos.cambiar_plan_suscripcion(MP_ID, "elite", 77) is False


# ── La ruta, con Mercado Pago y la base simulados ───────────────────────────────────────────────────────────────────────────

class _Cursor:
    rowcount = 1

    def __init__(self, fila, escrituras):
        self.fila, self.escrituras = fila, escrituras

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        if not sql.startswith("SELECT"):
            self.escrituras.append((sql, params))

    def fetchone(self):
        return self.fila


class _Conexion:
    def __init__(self, fila, escrituras):
        self.fila, self.escrituras = fila, escrituras

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor(self.fila, self.escrituras)


@pytest.fixture
def entorno(monkeypatch):
    """Ejecuta la vista de /suscripcion/iniciar (sin el login) con la base y Mercado Pago simulados. Devuelve una función: llamar(plan, plan_actual, mp_id, estado_en_mp)."""
    import app as modulo_app
    monkeypatch.setattr(config, "MP_ACCESS_TOKEN", "APP_USR-de-prueba")
    llamadas = {"escrituras": [], "creadas": [], "canceladas": [], "cambiadas": [], "auditadas": []}
    monkeypatch.setattr(pagos, "crear_link_suscripcion", lambda plan, uid, email, back: llamadas["creadas"].append((plan, uid)) or ("https://mp.test/checkout", "nueva-id"))
    monkeypatch.setattr(pagos, "cancelar_suscripcion", lambda mp_id: llamadas["canceladas"].append(mp_id) or True)
    monkeypatch.setattr(auditoria, "registrar", lambda accion, detalle=None, **k: llamadas["auditadas"].append((accion, detalle)))

    def llamar(plan, plan_actual, mp_id, estado_en_mp=None, cambio_ok=True):
        monkeypatch.setattr(modulo_app.db, "conexion_usuario", lambda *a, **k: _Conexion(("usuario@correo.com", plan_actual, mp_id), llamadas["escrituras"]))
        monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: {"status": estado_en_mp} if estado_en_mp else None)
        monkeypatch.setattr(pagos, "cambiar_plan_suscripcion", lambda mp, p, uid: llamadas["cambiadas"].append((mp, p, uid)) or cambio_ok)
        for clave in llamadas:
            llamadas[clave].clear()
        with modulo_app.app.test_request_context("/suscripcion/iniciar", method="POST", data={"plan": plan}):
            from flask import g
            g.usuario_id, g.cuenta_id = 77, 5
            respuesta = modulo_app.suscripcion_iniciar.__wrapped__()
        return respuesta.location, llamadas

    return llamar


def test_un_usuario_base_que_mejora_a_elite_cambia_su_suscripcion_y_no_se_crea_otra(entorno):
    destino, llamadas = entorno("elite", "base", MP_ID, "authorized")
    assert destino.endswith("/planes?aviso=plan_cambiado")
    assert llamadas["cambiadas"] == [(MP_ID, "elite", 77)]
    assert llamadas["creadas"] == [] and llamadas["canceladas"] == []                       # NO hay segunda suscripción
    assert [e for e in llamadas["escrituras"] if e[0].startswith("UPDATE usuarios SET plan")] == [("UPDATE usuarios SET plan = %s WHERE id = %s", ("elite", 77))]
    assert llamadas["auditadas"] == [("suscripcion_cambiar_plan", {"de": "base", "a": "elite", "preapproval_id": MP_ID})]


def test_si_mercado_pago_no_acepta_el_cambio_el_plan_no_se_toca(entorno):
    destino, llamadas = entorno("elite", "base", MP_ID, "authorized", cambio_ok=False)
    assert destino.endswith("/planes?aviso=mp_error")
    assert llamadas["escrituras"] == [] and llamadas["creadas"] == [] and llamadas["auditadas"] == []


def test_si_la_suscripcion_anterior_ya_no_esta_al_dia_se_cancela_y_se_arma_una_nueva(entorno):
    destino, llamadas = entorno("elite", "base", MP_ID, "paused")
    assert destino == "https://mp.test/checkout"
    assert llamadas["canceladas"] == [MP_ID] and llamadas["creadas"] == [("elite", 77)]      # la vieja se cancela ANTES: nunca quedan dos vivas
    assert llamadas["cambiadas"] == []


def test_si_mercado_pago_no_responde_no_se_arma_nada_porque_podrian_quedar_dos_cobrando(entorno):
    destino, llamadas = entorno("elite", "base", MP_ID, None)
    assert destino.endswith("/planes?aviso=mp_error")
    assert llamadas["creadas"] == [] and llamadas["canceladas"] == [] and llamadas["cambiadas"] == [] and llamadas["escrituras"] == []


def test_una_cuenta_de_cortesia_nunca_arma_un_cobro(entorno):
    for plan_pedido in ("base", "elite"):
        destino, llamadas = entorno(plan_pedido, "elite", None)
        assert destino.endswith("/planes?aviso=plan_a_mano")
        assert llamadas["creadas"] == [] and llamadas["cambiadas"] == [] and llamadas["escrituras"] == []


def test_bajar_de_elite_a_base_y_pedir_el_mismo_plan_no_tocan_nada(entorno):
    destino, llamadas = entorno("base", "elite", MP_ID, "authorized")
    assert destino.endswith("/planes?aviso=bajar_no_disponible")
    destino, _ = entorno("elite", "elite", MP_ID, "authorized")
    assert destino.endswith("/planes?aviso=mismo_plan")
    assert llamadas["cambiadas"] == [] and llamadas["creadas"] == []


def test_un_usuario_en_prueba_arma_su_primera_suscripcion(entorno):
    destino, llamadas = entorno("base", "trial", None)
    assert destino == "https://mp.test/checkout"
    assert llamadas["creadas"] == [("base", 77)] and llamadas["canceladas"] == []
    assert any(e[0].startswith("UPDATE usuarios SET mp_suscripcion_id") for e in llamadas["escrituras"])
    assert llamadas["auditadas"] == [("suscripcion_iniciar", {"plan": "base", "preapproval_id": "nueva-id"})]       # arma un cobro: queda registrado


# ── El aviso tardío de una suscripción vieja no baja el plan nuevo ──────────────────────────────────────────────────────────

def test_el_aviso_de_cancelacion_solo_baja_el_plan_si_es_de_la_suscripcion_guardada(monkeypatch):
    import app as modulo_app
    escrituras = []
    monkeypatch.setattr(config, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: {"status": "cancelled", "external_reference": "base|77"})
    monkeypatch.setattr(modulo_app.db, "conexion_admin", lambda: _Conexion(None, escrituras))
    r = modulo_app.app.test_client().post(f"/webhook/mercadopago?data.id={MP_ID}&type=subscription_preapproval", json={"data": {"id": MP_ID}})
    assert r.status_code == 200
    sql, params = escrituras[0]
    assert "mp_suscripcion_id IS NULL OR mp_suscripcion_id = %s" in sql and params == (77, MP_ID)


# ── La pantalla ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _planes(**contexto):
    import app as modulo_app
    from flask import render_template
    base = dict(plan_actual="base", dias_trial=None, aviso=None, aviso_ok=False, proximo_cobro=None, pagos_habilitados=True)
    with modulo_app.app.test_request_context("/planes"):
        return render_template("planes.html", **{**base, **contexto})


def test_mejorar_a_elite_pide_confirmar_mostrando_el_antes_y_el_despues():
    html = _planes(proximo_cobro=datetime.now(timezone.utc) + timedelta(days=20))
    assert "Mejorar a Elite" in html and 'data-click="confirmarAccion"' in html
    argumentos = html.split("data-click-args='", 1)[1].split("'", 1)[0]
    mensaje, formulario, boton, detalle = json.loads(argumentos.replace("&#34;", '"'))
    assert formulario == "$form" and boton == "Pasar a Elite"
    assert "$40.000" in detalle and "$99.000" in detalle and "se cobra dos veces" in detalle and "próxima renovación (" in detalle
    assert "onclick" not in html.split("Mejorar a Elite")[0][-400:]            # sin manejadores inline nuevos


def test_el_aviso_de_cambio_hecho_se_muestra_como_exito():
    html = _planes(aviso="Listo: tu suscripción pasó al nuevo plan.", aviso_ok=True)
    assert "planes-aviso-ok" in html and 'role="status"' in html
    assert 'role="alert"' not in _planes(aviso=None)

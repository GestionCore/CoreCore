"""El webhook de Mercado Pago: qué id usa para consultar la suscripción y que un aviso bien firmado llegue hasta la base."""
import hashlib
import hmac

import pytest

import pagos

SECRETO = "secreto-de-prueba"
PREAPPROVAL = "6e27f74e29fb44abbfa583901801f3e3"


def _firma(data_id, request_id="req-1", ts="1704908010"):
    manifiesto = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return f"ts={ts},v1=" + hmac.new(SECRETO.encode(), manifiesto.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def consultas(monkeypatch):
    """Registra a qué suscripción se le pregunta el estado y devuelve una autorizada del usuario 77 (plan base)."""
    pedidas = []

    def falso(preapproval_id):
        pedidas.append(preapproval_id)
        return {"status": "authorized", "external_reference": "base|77"}

    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", falso)
    return pedidas


def test_en_un_aviso_real_el_id_de_la_suscripcion_es_data_id_y_no_el_numero_del_aviso(consultas):
    # En el formato nuevo `id` es el número del AVISO (distinto del recurso): consultar con él nunca encontraba la suscripción.
    cuerpo = {"action": "updated", "type": "subscription_preapproval", "id": "125000000001", "data": {"id": PREAPPROVAL}}
    assert pagos.procesar_webhook(cuerpo) == (77, "base", PREAPPROVAL)
    assert consultas == [PREAPPROVAL]


def test_el_id_de_la_url_manda_y_el_tipo_puede_venir_solo_en_la_url(consultas):
    assert pagos.procesar_webhook({}, data_id_url=PREAPPROVAL, tipo_url="subscription_preapproval") == (77, "base", PREAPPROVAL)
    assert consultas == [PREAPPROVAL]


def test_los_avisos_de_cobro_y_otros_temas_no_consultan_nada(consultas):
    assert pagos.procesar_webhook({"type": "subscription_authorized_payment", "data": {"id": "7032716687"}}) is None
    assert pagos.procesar_webhook({}, data_id_url="1", tipo_url="payment") is None
    assert consultas == []


def test_una_suscripcion_cancelada_deja_el_plan_cancelado(monkeypatch):
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: {"status": "cancelled", "external_reference": "elite|9"})
    assert pagos.procesar_webhook({"type": "subscription_preapproval", "data": {"id": PREAPPROVAL}}) == (9, "cancelado", PREAPPROVAL)


def test_sin_referencia_valida_o_sin_respuesta_no_se_toca_a_nadie(monkeypatch):
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: {"status": "authorized", "external_reference": "sin-barra"})
    assert pagos.procesar_webhook({"type": "subscription_preapproval", "data": {"id": PREAPPROVAL}}) is None
    monkeypatch.setattr(pagos, "obtener_estado_suscripcion", lambda _id: None)
    assert pagos.procesar_webhook({"type": "subscription_preapproval", "data": {"id": PREAPPROVAL}}) is None


def test_el_diagnostico_prueba_tambien_el_id_del_aviso():
    firmada = _firma("125000000001")                      # por si Mercado Pago firmara con el número del aviso
    diag = pagos.diagnostico_firma(firmada, "req-1", PREAPPROVAL, SECRETO, ids_alternativos={"id_del_aviso": "125000000001"})
    assert "coincide=id_del_aviso" in diag


class _Cursor:
    def __init__(self, registro):
        self.registro = registro

    def execute(self, sql, params=None):
        self.registro.append((" ".join(sql.split()), params))


class _Conexion:
    def __init__(self, registro):
        self.registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor(self.registro)


def test_un_aviso_bien_firmado_actualiza_el_plan_del_usuario(monkeypatch, consultas):
    import app as modulo_app
    import config
    escrituras = []
    monkeypatch.setattr(config, "MP_WEBHOOK_SECRET", SECRETO)
    monkeypatch.setattr(modulo_app.db, "conexion_admin", lambda: _Conexion(escrituras))
    r = modulo_app.app.test_client().post(f"/webhook/mercadopago?data.id={PREAPPROVAL}&type=subscription_preapproval",
                                          json={"action": "updated", "id": "125000000001", "data": {"id": PREAPPROVAL}},
                                          headers={"x-signature": _firma(PREAPPROVAL), "x-request-id": "req-1"})
    assert r.status_code == 200
    assert consultas == [PREAPPROVAL]
    assert len(escrituras) == 1 and escrituras[0][1] == ("base", PREAPPROVAL, 77)


def test_un_cuerpo_que_no_es_un_objeto_no_rompe_el_webhook(monkeypatch):
    import app as modulo_app
    import config
    monkeypatch.setattr(config, "MP_WEBHOOK_SECRET", SECRETO)
    for cuerpo in ([1, 2], "texto", None):
        r = modulo_app.app.test_client().post("/webhook/mercadopago", json=cuerpo, headers={"x-signature": "ts=1,v1=00"})
        assert r.status_code == 401        # sin firma válida se rechaza; lo importante es que no sea un 500

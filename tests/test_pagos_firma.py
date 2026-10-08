import hashlib
import hmac

import pagos

SECRETO = "secreto-de-prueba"


def _firmar(data_id, request_id, ts, secreto=SECRETO):
    manifiesto = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return f"ts={ts},v1=" + hmac.new(secreto.encode(), manifiesto.encode(), hashlib.sha256).hexdigest()


def test_una_firma_correcta_pasa():
    assert pagos.firma_valida(_firmar("2c938084726fca480172750000000000", "req-1", "1704908010"), "req-1", "2c938084726fca480172750000000000", SECRETO)


def test_el_id_alfanumerico_se_firma_en_minusculas():
    assert pagos.firma_valida(_firmar("abc123def", "r", "1"), "r", "ABC123DEF", SECRETO)


def test_firma_de_otro_secreto_o_alterada_se_rechaza():
    firma = _firmar("123", "req-1", "1704908010", secreto="otro")
    assert not pagos.firma_valida(firma, "req-1", "123", SECRETO)
    buena = _firmar("123", "req-1", "1704908010")
    assert not pagos.firma_valida(buena, "req-1", "124", SECRETO)          # otro id
    assert not pagos.firma_valida(buena, "req-2", "123", SECRETO)          # otro request-id
    assert not pagos.firma_valida(buena.replace("ts=1704908010", "ts=1704908011"), "req-1", "123", SECRETO)


def test_sin_cabecera_o_mal_formada_se_rechaza_cuando_hay_secreto():
    assert not pagos.firma_valida(None, "r", "1", SECRETO)
    assert not pagos.firma_valida("", "r", "1", SECRETO)
    assert not pagos.firma_valida("basura", "r", "1", SECRETO)
    assert not pagos.firma_valida("ts=1", "r", "1", SECRETO)               # falta v1


def test_el_diagnostico_dice_si_la_firma_coincide_con_alguna_variante_y_nunca_muestra_la_clave():
    buena = _firmar("123", "req-1", "1704908010")
    assert "coincide=estandar" in pagos.diagnostico_firma(buena, "req-1", "123", SECRETO)
    sin_request = "ts=1704908010,v1=" + hmac.new(SECRETO.encode(), b"id:123;ts:1704908010;", hashlib.sha256).hexdigest()
    assert "coincide=sin_request_id" in pagos.diagnostico_firma(sin_request, "req-1", "123", SECRETO)
    con_espacios = "ts=1704908010,v1=" + hmac.new(SECRETO.encode(), b"id:123 request-id:req-1 ts:1704908010", hashlib.sha256).hexdigest()
    assert "coincide=con_espacios" in pagos.diagnostico_firma(con_espacios, "req-1", "123", SECRETO)
    sin_final = "ts=1704908010,v1=" + hmac.new(SECRETO.encode(), b"id:123;request-id:req-1;ts:1704908010", hashlib.sha256).hexdigest()
    assert "coincide=sin_punto_y_coma_final" in pagos.diagnostico_firma(sin_final, "req-1", "123", SECRETO)
    otra_clave = _firmar("123", "req-1", "1704908010", secreto="otra")
    diag = pagos.diagnostico_firma(otra_clave, "req-1", "123", SECRETO)
    assert "coincide=ninguna" in diag
    assert SECRETO not in diag
    assert "firma=no" in pagos.diagnostico_firma(None, None, None, SECRETO)       # sin cabeceras: no explota


def test_el_webhook_rechazado_deja_el_diagnostico_en_el_log(monkeypatch, caplog):
    import app as modulo_app
    import config
    monkeypatch.setattr(config, "MP_WEBHOOK_SECRET", SECRETO)
    with caplog.at_level("WARNING"):
        r = modulo_app.app.test_client().post("/webhook/mercadopago?data.id=abc&type=subscription_preapproval", json={}, headers={"x-signature": "ts=1,v1=00", "x-request-id": "r"})
    assert r.status_code == 401
    assert "coincide=ninguna" in caplog.text and "subscription_preapproval" in caplog.text
    assert SECRETO not in caplog.text


def test_sin_secreto_configurado_no_se_puede_verificar_y_se_acepta():
    assert pagos.firma_valida(None, None, None, "")
    assert pagos.firma_valida("cualquier cosa", "r", "1", None)

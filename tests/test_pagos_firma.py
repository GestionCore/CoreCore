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


def test_sin_secreto_configurado_no_se_puede_verificar_y_se_acepta():
    assert pagos.firma_valida(None, None, None, "")
    assert pagos.firma_valida("cualquier cosa", "r", "1", None)

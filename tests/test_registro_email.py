import pytest

from auth.registro import email_de_meli, email_pendiente


@pytest.mark.parametrize("dato, esperado", [
    ({"email": "Vendedor@Gmail.com"}, "vendedor@gmail.com"),
    ({"email": "  a@b.co  "}, "a@b.co"),
    ({"email": ""}, None),
    ({"email": None}, None),
    ({}, None),
    ({"email": "sin-arroba"}, None),
    ({"email": "raro@sinpunto"}, None),
    ({"email": "meli-1@pendiente.corelux.app"}, None),     # el provisorio nunca cuenta como real
])
def test_email_de_meli(dato, esperado):
    assert email_de_meli(dato) == esperado


def test_el_email_provisorio_tiene_el_formato_de_siempre():
    assert email_pendiente(619292584) == "meli-619292584@pendiente.corelux.app"

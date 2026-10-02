import pytest

import publicacion_edicion as pe

ACTUAL = {"titulo": "Campera de jean hombre", "precio": 54999.0, "estado": "active"}


def test_solo_se_manda_lo_que_cambio():
    """Antes iban título, precio y estado siempre: con ventas MeLi rechaza el título y con él, el precio que era lo único que se había cambiado."""
    payload, errores = pe.armar_cambios(ACTUAL, {"titulo": "Campera de jean hombre", "precio": "59999", "estado": "active"})
    assert errores == [] and payload == {"price": 59999.0}


def test_sin_cambios_no_se_manda_nada():
    assert pe.armar_cambios(ACTUAL, {"titulo": "  Campera   de jean hombre ", "precio": 54999.001, "estado": "active"}) == ({}, [])


def test_se_puede_pausar_y_cambiar_el_titulo():
    payload, errores = pe.armar_cambios(ACTUAL, {"titulo": "Campera de jean negra", "precio": 54999, "estado": "paused"})
    assert errores == [] and payload == {"title": "Campera de jean negra", "status": "paused"}


@pytest.mark.parametrize("estado", ["closed", "inactive", "cualquiera"])
def test_finalizar_no_se_ofrece_desde_el_panel(estado):
    """"closed" finaliza la publicación en Mercado Libre y no tiene vuelta atrás."""
    payload, errores = pe.armar_cambios(ACTUAL, {"estado": estado})
    assert payload == {} and "solo se puede activar o pausar" in errores[0]


def test_una_publicacion_finalizada_no_se_puede_reactivar_desde_aca():
    payload, errores = pe.armar_cambios({**ACTUAL, "estado": "closed"}, {"estado": "active"})
    assert payload == {} and "Finalizada" in errores[0]


@pytest.mark.parametrize("precio", ["0", "-5", "abc", "nan", "inf"])
def test_un_precio_invalido_se_rechaza_en_vez_de_mandarse_como_cero(precio):
    payload, errores = pe.armar_cambios(ACTUAL, {"precio": precio})
    assert payload == {} and "precio" in errores[0]


def test_precio_vacio_no_cambia_el_precio():
    assert pe.armar_cambios(ACTUAL, {"precio": ""}) == ({}, [])


def test_titulo_vacio_o_demasiado_largo():
    assert pe.armar_cambios(ACTUAL, {"titulo": "   "})[1] == ["El título no puede quedar vacío."]
    assert "pasar de" in pe.armar_cambios(ACTUAL, {"titulo": "x" * 121})[1][0]
    assert pe.armar_cambios(ACTUAL, {"titulo": "x" * 98})[0] == {"title": "x" * 98}     # los títulos de ropa de la cuenta de prueba tienen 79-98 caracteres


def test_el_rechazo_de_mercado_libre_se_explica_en_una_frase():
    cuerpo = {"message": "Validation error", "cause": [{"code": "item.title.not_modifiable", "message": "Title is not modifiable"}]}
    assert "ya tiene ventas" in pe.explicar_error_meli(400, cuerpo)
    assert "reconectar" in pe.explicar_error_meli(403, {})
    assert "esperar" in pe.explicar_error_meli(429, None)
    assert "no respondió bien" in pe.explicar_error_meli(503, None)
    assert "No se modificó nada" in pe.explicar_error_meli(400, {"message": "x"})


def test_resumen_de_cambios_para_la_confirmacion():
    payload = {"price": 59999.0, "status": "paused", "title": "Nuevo"}
    lineas = pe.resumen_cambios(ACTUAL, payload)
    assert lineas == ["Título: «Campera de jean hombre» → «Nuevo»", "Precio: $54.999 → $59.999", "Estado: Activa → Pausada"]

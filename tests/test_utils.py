import pytest
from utils import extraer_talle, limpiar_titulo_modelo


@pytest.mark.parametrize("titulo, esperado", [
    ("Campera Jean Negro XL", "XL"),
    ("Campera Jean Negro Talle L", "L"),
    ("Remera Algodon Talle 3", "3"),
    ("Chaleco Inflable Lisa 7", "7"),              # número suelto AL FINAL: es talle
    ("Combo 2 Termos Acero Inoxidable 1l", "Único"),  # número en el medio: no es talle
    ("Perfume 50 ml", "Único"),
    ("Pack 12 Medias", "Único"),
    ("Termo Acero 1 Litro", "Único"),
    ("", "Único"),
    (None, "Único"),
])
def test_extraer_talle_del_titulo(titulo, esperado):
    assert extraer_talle(titulo) == esperado


def test_el_talle_real_de_mercado_libre_gana_sobre_el_titulo():
    assert extraer_talle("Medias Pack Docena", "38-43") == "38-43"
    assert extraer_talle("Campera Negro XL", "m") == "M"
    assert extraer_talle("Campera Negro XL", "Único") == "XL"      # "Único" no es un dato: se mira el título


def test_clave_de_modelo_agrupa_los_talles():
    base = "Campera De Jean Hombre Negro"
    assert limpiar_titulo_modelo(base + " XL") == limpiar_titulo_modelo(base + " L") == base
    assert limpiar_titulo_modelo(base + " Talle 3") == base
    assert limpiar_titulo_modelo(None) == ""


def test_dos_productos_distintos_no_se_agrupan():
    assert limpiar_titulo_modelo("Pack 12 Medias") != limpiar_titulo_modelo("Pack 6 Medias")

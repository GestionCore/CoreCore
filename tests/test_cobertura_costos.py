from datetime import date

from costos import cobertura_de_costos, UMBRAL_AVISO_SIN_COSTO
from tests.conftest import CursorFalso


def _medir(facturado, sin_costo, publicaciones):
    return cobertura_de_costos(CursorFalso([(facturado, sin_costo, publicaciones)]), date(2026, 9, 1), date(2026, 9, 30))


def test_con_todo_cubierto_no_se_avisa():
    r = _medir(1_000_000, 0, 0)
    assert r["pct_sin_costo"] == 0 and r["avisar"] is False


def test_se_mide_por_plata_no_por_cantidad_de_publicaciones():
    r = _medir(10_000_000, 1_070_000, 7)
    assert r["pct_sin_costo"] == 10.7 and r["publicaciones"] == 7 and r["avisar"] is True


def test_por_debajo_del_umbral_no_molesta():
    r = _medir(1_000_000, 10 * UMBRAL_AVISO_SIN_COSTO * 100 - 1, 1)       # justo por debajo del umbral
    assert r["avisar"] is False


def test_sin_ventas_no_hay_nada_que_avisar():
    r = _medir(0, 0, 0)
    assert r["pct_sin_costo"] == 0 and r["avisar"] is False


def test_sin_ningun_costo_es_el_cien_por_ciento():
    r = _medir(500_000, 500_000, 4)
    assert r["pct_sin_costo"] == 100.0 and r["avisar"] is True

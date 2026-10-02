import pytest

from ventas_sync import _fecha_hora_argentina


@pytest.mark.parametrize("raw, esperado", [
    ("2026-09-30T23:30:00.000-04:00", ("2026-10-01", "00:30:00")),      # la venta de 00:30 argentina ya no cae en el día anterior
    ("2026-10-01T10:00:00.000-04:00", ("2026-10-01", "11:00:00")),
    ("2026-10-01T03:30:00.000Z", ("2026-10-01", "00:30:00")),            # UTC
    ("2026-10-01T12:00:00.000-03:00", ("2026-10-01", "12:00:00")),       # ya en hora argentina
    ("2026-10-01T12:00:00", ("2026-10-01", "12:00:00")),                  # sin offset: se asume argentina
])
def test_fecha_hora_argentina(raw, esperado):
    assert _fecha_hora_argentina(raw) == esperado


@pytest.mark.parametrize("raw", ["", None, "no es una fecha"])
def test_si_no_se_puede_leer_usa_el_momento_actual(raw):
    fecha, hora = _fecha_hora_argentina(raw)
    assert len(fecha) == 10 and len(hora) == 8


def test_el_insert_marca_las_filas_como_normalizadas():
    fuente = open("ventas_sync.py", encoding="utf-8").read()
    assert "hora_normalizada" in fuente and "true)\n                ON CONFLICT" in fuente.replace("\r\n", "\n")

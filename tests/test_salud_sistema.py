import pytest

from salud_sistema import _duracion, estado_de_cuenta


@pytest.mark.parametrize("args, tono", [
    ((False, True, True, 1), "danger"),        # desconectada
    ((True, False, True, 1), "danger"),        # sin tokens
    ((True, True, False, None), "warn"),       # primera sincronización
    ((True, True, True, None), "warn"),        # nunca sincronizó ventas
    ((True, True, True, 2), "ok"),
    ((True, True, True, 12), "ok"),
    ((True, True, True, 13), "warn"),          # se salteó algún ciclo
    ((True, True, True, 31), "danger"),
])
def test_estado_de_cuenta(args, tono):
    assert estado_de_cuenta(*args)[0] == tono


def test_una_cuenta_desconectada_gana_sobre_cualquier_otro_estado():
    assert estado_de_cuenta(False, False, False, None)[0] == "danger"
    assert "volver a conectar" in estado_de_cuenta(False, True, True, 1)[1]


@pytest.mark.parametrize("minutos, texto", [(5, "5 min"), (59, "59 min"), (60, "1 h"), (180, "3 h"), (60 * 48, "2 días")])
def test_duracion_legible(minutos, texto):
    assert _duracion(minutos) == texto


def test_migraciones_pendientes_compara_por_el_prefijo_numerico():
    from salud_sistema import migraciones_pendientes
    disco = ["0001_alertas.sql", "0002_soft_delete.sql", "0003_otra.sql"]
    assert migraciones_pendientes(disco, {"0001", "0002", "0003"}) == []
    assert migraciones_pendientes(disco, {"0001"}) == ["0002_soft_delete.sql", "0003_otra.sql"]


def test_el_runner_y_el_panel_leen_las_versiones_igual():
    """migrate.py guarda el prefijo numérico: si cambia el formato, el panel mostraría todo como pendiente."""
    import re
    fuente = open("migrate.py", encoding="utf-8").read()
    assert re.search(r"match\.group\(1\)", fuente)

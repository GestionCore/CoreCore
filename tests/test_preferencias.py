"""Margen mínimo de la cuenta: validación del valor y tolerancia a que la migración todavía no esté aplicada."""
import contextlib

import pytest

import db
import preferencias as p


@pytest.mark.parametrize("entrada, esperado", [
    ("15", 15.0), (15, 15.0), ("12,5", 12.5), ("12.55", 12.6), (" 0 ", 0.0), (60, 60.0), ("30.04", 30.0),
    ("", None), (None, None), ("abc", None), (-1, None), ("60,1", None), (61, None), ("nan", None), ("inf", None),
])
def test_normalizar_margen(entrada, esperado):
    assert p.normalizar_margen(entrada) == esperado


class _Cursor:
    def __init__(self):
        self.consultas = []

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))


def test_guardar_solo_escribe_valores_validos():
    cursor = _Cursor()
    assert p.guardar_margen_minimo(cursor, 7, "22,5") == 22.5
    assert cursor.consultas == [("UPDATE cuentas_meli SET margen_minimo = %s WHERE id = %s", (22.5, 7))]
    assert p.guardar_margen_minimo(cursor, 7, "mucho") is None
    assert len(cursor.consultas) == 1                      # lo inválido no toca la base


def test_sin_la_columna_se_usa_el_valor_por_defecto(monkeypatch):
    @contextlib.contextmanager
    def conexion(*a, **k):
        raise RuntimeError('column "margen_minimo" does not exist')
        yield

    monkeypatch.setattr(db, "conexion_usuario", conexion)
    assert p.margenes_de_usuario(1) == {}


def test_lee_el_margen_de_cada_cuenta(monkeypatch):
    class C:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return [(2, 15), (7, 22.5)]

    @contextlib.contextmanager
    def conexion(*a, **k):
        yield type("Con", (), {"cursor": lambda self: C()})()

    monkeypatch.setattr(db, "conexion_usuario", conexion)
    assert p.margenes_de_usuario(3) == {2: 15.0, 7: 22.5}

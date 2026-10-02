import contextlib

import pytest

import sincronizador


@pytest.mark.parametrize("minutos, en_curso, desconectada, esperado", [
    (2, True, False, "normal"),
    (3, False, False, "normal"),            # recién arrancó: todavía no es motivo de aviso
    (12, False, False, "atascada"),         # pasó el tiempo y no hay nada corriendo
    (12, True, False, "normal"),            # corre: es solo una cuenta grande
    (30, True, False, "lenta"),
    (1, False, True, "desconectada"),       # esperar no sirve: hay que reconectar
    (40, False, True, "desconectada"),
])
def test_diagnostico_de_la_primera_sincronizacion(minutos, en_curso, desconectada, esperado):
    assert sincronizador.diagnostico_sync_inicial(minutos, en_curso, desconectada) == esperado


class _Base:
    def __init__(self):
        self.sql = []

    @contextlib.contextmanager
    def conexion(self, *a, **k):
        base = self

        class Cur:
            def execute(self, sql, params=None):
                base.sql.append(" ".join(sql.split()))

            def fetchone(self):
                return (123,)

        yield type("C", (), {"cursor": lambda s: Cur()})()


def _correr(monkeypatch, catalogo):
    base = _Base()
    monkeypatch.setattr(sincronizador.db, "conexion_usuario", base.conexion)
    monkeypatch.setattr(sincronizador.token_manager, "asegurar_token_valido", lambda c: "tok")
    monkeypatch.setattr(sincronizador, "sincronizar_catalogo", catalogo)
    monkeypatch.setattr(sincronizador.ventas_sync, "sincronizar_ventas", lambda *a, **k: None)
    monkeypatch.setattr(sincronizador.devoluciones_sync, "sincronizar_posventa", lambda *a, **k: None)
    monkeypatch.setattr(sincronizador.capacidades, "refrescar_si_hace_falta", lambda *a, **k: {})
    monkeypatch.setattr(sincronizador.enriquecimiento, "refrescar_todo", lambda *a, **k: None)
    sincronizador._sincronizar_todo_interno(1, 1)
    return base.sql


def test_si_el_catalogo_falla_la_cuenta_no_se_marca_como_completa(monkeypatch):
    """Antes una falla acá cortaba todo sin dejar rastro; ahora se reintenta en la próxima pasada en vez de mostrar pantallas sin publicaciones."""
    def falla(*a, **k):
        raise ConnectionError("MeLi no responde")

    sql = _correr(monkeypatch, falla)
    assert not any("sincronizacion_inicial_completa = true" in s for s in sql)


def test_si_todo_sale_bien_se_marca_completa(monkeypatch):
    sql = _correr(monkeypatch, lambda *a, **k: None)
    assert any("sincronizacion_inicial_completa = true" in s for s in sql)

"""La ruta que guarda el margen mínimo: valida, guarda para la cuenta activa y refresca el valor que ven las pantallas. Sin base (dobles)."""
import contextlib
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402
import db  # noqa: E402
import preferencias  # noqa: E402


class _Cursor:
    def __init__(self):
        self.consultas = []

    def execute(self, sql, params=None):
        self.consultas.append((" ".join(sql.split()), params))


def _llamar(monkeypatch, cuerpo):
    cursor = _Cursor()

    @contextlib.contextmanager
    def conexion(*a, **k):
        yield type("Con", (), {"cursor": lambda self: cursor})()

    monkeypatch.setattr(db, "conexion_usuario", conexion)
    monkeypatch.setattr(preferencias, "margenes_de_usuario", lambda usuario_id: {7: 22.5})
    guardado = {}
    monkeypatch.setattr(aplicacion, "cache_guardar", lambda clave, valor, timeout=None: guardado.update(clave=clave, valor=valor))
    funcion = aplicacion.api_cuenta_margen_minimo
    while hasattr(funcion, "__wrapped__"):
        funcion = funcion.__wrapped__
    with aplicacion.app.test_request_context(json=cuerpo, method="POST"):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = 3, 7
        r = funcion()
        respuesta, codigo = (r if isinstance(r, tuple) else (r, 200))
        return respuesta.get_json(), codigo, cursor.consultas, guardado


def test_guarda_el_margen_de_la_cuenta_activa_y_refresca_el_valor_que_ven_las_pantallas(monkeypatch):
    cuerpo, codigo, consultas, guardado = _llamar(monkeypatch, {"valor": "22,5"})
    assert codigo == 200 and cuerpo == {"ok": True, "margen_minimo": 22.5}
    assert consultas == [("UPDATE cuentas_meli SET margen_minimo = %s WHERE id = %s", (22.5, 7))]
    assert guardado["valor"] == {"7": 22.5}


@pytest.mark.parametrize("valor", ["", "abc", -3, 80, None])
def test_un_valor_invalido_no_toca_nada(monkeypatch, valor):
    cuerpo, codigo, consultas, guardado = _llamar(monkeypatch, {"valor": valor})
    assert codigo == 400 and cuerpo["ok"] is False and consultas == [] and guardado == {}

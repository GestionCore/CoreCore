import pytest

import ia_asistente as ia


class Resp:
    def __init__(self, contenido, codigo=200, finish="stop"):
        self.status_code, self._c, self._f = codigo, contenido, finish

    def json(self):
        return {"choices": [{"message": {"content": self._c}, "finish_reason": self._f}]}


@pytest.fixture(autouse=True)
def _con_clave(monkeypatch):
    monkeypatch.setattr(ia, "IA_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(ia.time if hasattr(ia, "time") else __import__("time"), "sleep", lambda s: None)


def test_deepseek_apaga_el_razonamiento_por_defecto(monkeypatch):
    monkeypatch.delenv("IA_PARAMETROS_EXTRA", raising=False)
    monkeypatch.setattr(ia, "IA_BASE_URL", "https://api.deepseek.com")
    assert ia.parametros_extra() == {"thinking": {"type": "disabled"}}


def test_otro_proveedor_no_recibe_parametros_que_no_conoce(monkeypatch):
    monkeypatch.delenv("IA_PARAMETROS_EXTRA", raising=False)
    monkeypatch.setattr(ia, "IA_BASE_URL", "https://api.openai.com/v1")
    assert ia.parametros_extra() == {}


def test_la_variable_de_entorno_manda_sobre_el_default(monkeypatch):
    monkeypatch.setattr(ia, "IA_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("IA_PARAMETROS_EXTRA", "{}")
    assert ia.parametros_extra() == {}
    monkeypatch.setenv("IA_PARAMETROS_EXTRA", '{"reasoning_effort": "none"}')
    assert ia.parametros_extra() == {"reasoning_effort": "none"}
    monkeypatch.setenv("IA_PARAMETROS_EXTRA", "esto no es json")
    assert ia.parametros_extra() == {}


def test_una_respuesta_vacia_se_reintenta_con_mas_presupuesto(monkeypatch):
    presupuestos = []

    def post(url, **kw):
        presupuestos.append(kw["json"]["max_tokens"])
        return Resp("" if len(presupuestos) < 3 else "Listo.", finish="length" if len(presupuestos) < 3 else "stop")
    monkeypatch.setattr(ia.requests, "post", post)
    assert ia.preguntar_ia("sistema", "usuario", max_tokens=200) == (True, "Listo.")
    assert presupuestos == [200, 600, 1800]


def test_el_presupuesto_nunca_supera_el_maximo(monkeypatch):
    presupuestos = []
    monkeypatch.setattr(ia.requests, "post", lambda url, **kw: presupuestos.append(kw["json"]["max_tokens"]) or Resp(""))
    ok, _ = ia.preguntar_ia("s", "u", max_tokens=2000)
    assert not ok and max(presupuestos) == ia.MAXIMO_TOKENS


def test_los_parametros_extra_viajan_en_el_pedido(monkeypatch):
    enviados = []
    monkeypatch.setattr(ia, "IA_BASE_URL", "https://api.deepseek.com")
    monkeypatch.delenv("IA_PARAMETROS_EXTRA", raising=False)
    monkeypatch.setattr(ia.requests, "post", lambda url, **kw: enviados.append(kw["json"]) or Resp("hola"))
    ia.preguntar_ia("s", "u")
    assert enviados[0]["thinking"] == {"type": "disabled"}

"""Un rechazo de Mercado Libre se le explica a la persona con una frase (qué pasó y qué hacer), nunca con "403", un JSON o inglés de la API."""
import meli_errores as e


def test_cada_codigo_tiene_su_frase_y_ninguna_muestra_el_codigo():
    frases = {c: e.explicar_error_meli(c, None) for c in (401, 403, 404, 409, 429, 500, 503, 400, None)}
    assert "reconectar" in frases[401] and frases[401] == frases[403]
    assert "no encontró" in frases[404] and "recargá" in frases[409].lower()
    assert "esperar" in frases[429]
    assert "no respondió bien" in frases[500] and frases[500] == frases[503]
    assert "No se modificó nada" in frases[400] and frases[400] == frases[None]
    for frase in frases.values():
        assert not any(ch.isdigit() for ch in frase), frase


def test_una_causa_conocida_gana_sobre_el_codigo():
    cuerpo = {"cause": [{"code": "item.title.not_modifiable"}]}
    assert "ya tiene ventas" in e.explicar_error_meli(400, cuerpo)
    assert "ya tiene ventas" in e.explicar_error_meli(403, cuerpo)


def test_el_mensaje_de_una_causa_desconocida_se_acota():
    texto = e.explicar_error_meli(400, {"cause": [{"message": "x" * 500}]})
    assert texto.startswith("Mercado Libre no aceptó el cambio: ") and len(texto) < 200


class _Resp:
    def __init__(self, codigo, cuerpo=None, roto=False):
        self.status_code, self._c, self._roto = codigo, cuerpo, roto

    def json(self):
        if self._roto:
            raise ValueError("no es JSON")
        return self._c


def test_explicar_respuesta_lee_el_cuerpo_y_tolera_que_no_sea_json():
    assert "ya tiene ventas" in e.explicar_respuesta(_Resp(400, {"cause": [{"code": "item.title.not_modifiable"}]}))
    assert "reconectar" in e.explicar_respuesta(_Resp(403, roto=True))
    assert "reconectar" in e.explicar_respuesta(_Resp(403, ["no", "es", "dict"]))


def test_los_mensajes_conocidos_de_la_api_se_traducen():
    assert "no tiene stock" in e.explicar_error_meli(400, {"message": "Item has no stock"})
    assert "variante" in e.explicar_error_meli(400, {"message": "Item with variations: price must be set per variation"})
    assert "Item" not in e.explicar_error_meli(400, {"message": "Item has no stock"})

"""
Costo de publicidad por publicación (ads.obtener_costos_ads_por_item): un error de Mercado Libre NO es «sin gasto».
Hasta el 2026-10-08 una respuesta distinta de 200 (límite de pedidos, caída, permisos) o un corte omitía la publicación sin avisar: la ganancia salía inflada y el resultado a medias
se guardaba 5 minutos en caché. Ahora un 404 es «sin anuncio» (normal), cualquier otra cosa es un fallo que se cuenta, se avisa y no se guarda.
"""
import ads
import meli_http


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo or {}

    def json(self):
        return self._cuerpo


def _preparar(monkeypatch, respuestas):
    """`respuestas` = {id_meli: _Resp o una excepción}; devuelve la lista de ids consultados."""
    consultados = []

    def falso(url, **kw):
        item = url.split("/ads/")[1].split("?")[0]
        if item == "search":
            return _Resp(500)                                   # el listado masivo no responde: estas pruebas ejercitan el camino de respaldo, publicación por publicación
        consultados.append(item)
        r = respuestas[item]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(meli_http, "get", falso)
    ads._costos_cache.clear()
    ads._anuncios_cache.clear()
    return consultados


def _con_costo(valor):
    return _Resp(200, {"metrics": {"cost": valor}})


def test_los_404_son_sin_anuncio_y_los_ceros_son_sin_gasto_no_fallos(monkeypatch):
    _preparar(monkeypatch, {"MLA1": _con_costo(450.5), "MLA2": _Resp(404), "MLA3": _con_costo(0)})
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1", "MLA2", "MLA3"])
    assert dict(r) == {"MLA1": 450.5} and r.incompleto == 0


def test_un_error_de_mercado_libre_se_cuenta_como_fallo_y_no_se_guarda_en_cache(monkeypatch):
    consultados = _preparar(monkeypatch, {"MLA1": _con_costo(450.5), "MLA2": _Resp(429), "MLA3": _Resp(503), "MLA4": ConnectionError("se cortó"), "MLA5": _Resp(404)})
    ids = ["MLA1", "MLA2", "MLA3", "MLA4", "MLA5"]
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ids)
    assert dict(r) == {"MLA1": 450.5} and r.incompleto == 3                    # 429, 503 y el corte: tres fallos; el 404 no
    assert ads._costos_cache == {}                                              # el resultado a medias NO queda en caché…
    ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ids)
    assert len(consultados) == 10                                               # …así que la próxima vez se vuelve a preguntar (5 + 5)


def test_un_resultado_completo_si_se_guarda_en_cache(monkeypatch):
    consultados = _preparar(monkeypatch, {"MLA1": _con_costo(100), "MLA2": _Resp(404)})
    ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1", "MLA2"])
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1", "MLA2"])
    assert len(consultados) == 2 and dict(r) == {"MLA1": 100.0}                  # la segunda salió de la caché


def test_el_resultado_se_comporta_como_un_diccionario_comun(monkeypatch):
    _preparar(monkeypatch, {"MLA1": _con_costo(10)})
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert r.get("MLA1") == 10.0 and r.get("MLA9", 0.0) == 0.0 and list(r.items()) == [("MLA1", 10.0)]


def test_la_pantalla_avisa_cuando_la_lectura_de_publicidad_quedo_a_medias():
    plantilla = open("templates/metricas.html", encoding="utf-8").read()
    assert "{% elif ads_incompleto %}" in plantilla and "No pudimos leer la publicidad de" in plantilla
    assert 'ads_incompleto=datos.get("ads_incompleto", 0)' in open("app.py", encoding="utf-8").read()

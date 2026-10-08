"""
Publicidad por publicación con el listado masivo de anuncios (`/product_ads/ads/search`, 50 por página) en lugar de una consulta por publicación.
Medido con datos reales el 2026-10-08: 4 llamadas en 0,9 s contra 192 en 5,5 s, con los mismos números en 2 cuentas y períodos de 14 y 60 días.
Si el listado falla (o queda a medias), se vuelve a la consulta por publicación: un listado incompleto se leería como «no gastaron».
"""
import pytest

import ads
import meli_http


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo or {}

    def json(self):
        return self._cuerpo


def _anuncio(item_id, costo=0.0, ventas=0.0, unidades=0, clicks=0, prints=0, thumbnail="http://img/x.jpg"):
    return {"item_id": item_id, "title": f"Título {item_id}", "thumbnail": thumbnail,
            "metrics": {"cost": costo, "total_amount": ventas, "units_quantity": unidades, "clicks": clicks, "prints": prints}}


@pytest.fixture(autouse=True)
def caches_limpias():
    for cache in (ads._costos_cache, ads._metricas_item_cache, ads._anuncios_cache):
        cache.clear()
    yield
    for cache in (ads._costos_cache, ads._metricas_item_cache, ads._anuncios_cache):
        cache.clear()


def _listado(monkeypatch, anuncios, por_pagina=50, falla_en_pagina=None, por_publicacion=None):
    """Falsea Mercado Libre: sirve `anuncios` paginado en /ads/search y, si se pide, responde las consultas por publicación con `por_publicacion`."""
    llamadas = {"paginas": [], "individuales": []}

    def falso(url, **kw):
        if "/ads/search" in url:
            offset = int(url.split("offset=")[1].split("&")[0])
            assert f"limit={ads.ANUNCIOS_POR_PAGINA}" in url
            llamadas["paginas"].append(offset)
            if falla_en_pagina is not None and offset == falla_en_pagina:
                return _Resp(429)
            trozo = anuncios[offset:offset + por_pagina]
            return _Resp(200, {"paging": {"offset": offset, "total": len(anuncios), "limit": por_pagina}, "results": trozo})
        item = url.split("/ads/")[1].split("?")[0]
        llamadas["individuales"].append(item)
        return (por_publicacion or {}).get(item, _Resp(404))
    monkeypatch.setattr(meli_http, "get", falso)
    return llamadas


def test_el_listado_masivo_alcanza_para_las_metricas_de_cada_publicacion(monkeypatch):
    anuncios = [_anuncio("MLA1", costo=967.62, ventas=5000, unidades=2, clicks=11, prints=394), _anuncio("MLA2"), _anuncio("MLA3", prints=40), _anuncio("MLA4", costo=10)]
    llamadas = _listado(monkeypatch, anuncios)
    r = ads.obtener_metricas_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1", "MLA2", "MLA3"])
    assert llamadas["individuales"] == [] and llamadas["paginas"] == [0]                      # una sola página, ni una consulta por publicación
    assert set(r) == {"MLA1", "MLA3"}                                                          # MLA2 no gastó ni tuvo impresiones; MLA4 no es de las que se pidieron
    assert r["MLA1"] == {"costo": 967.62, "ventas": 5000.0, "unidades": 2, "clicks": 11, "prints": 394, "titulo": "Título MLA1", "thumbnail": "https://img/x.jpg"}


def test_el_costo_por_publicacion_sale_del_mismo_listado_y_no_queda_incompleto(monkeypatch):
    anuncios = [_anuncio("MLA1", costo=450.5), _anuncio("MLA2", costo=0), _anuncio("MLA3", costo=99.9), _anuncio("MLA9", costo=5)]
    llamadas = _listado(monkeypatch, anuncios)
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1", "MLA2", "MLA3", "MLA8"])
    assert dict(r) == {"MLA1": 450.5, "MLA3": 99.9} and r.incompleto == 0
    assert llamadas["individuales"] == []


def test_costos_y_metricas_comparten_la_misma_lectura_del_listado(monkeypatch):
    llamadas = _listado(monkeypatch, [_anuncio("MLA1", costo=10, prints=5)])
    ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    ads.obtener_metricas_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert llamadas["paginas"] == [0]                                                           # Publicidad y Ganancia Real no se piden lo mismo dos veces


def test_un_listado_de_varias_paginas_se_recorre_completo(monkeypatch):
    anuncios = [_anuncio(f"MLA{i}", costo=float(i + 1)) for i in range(120)]
    llamadas = _listado(monkeypatch, anuncios)
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", [f"MLA{i}" for i in range(120)])
    assert llamadas["paginas"] == [0, 50, 100] and len(r) == 120 and r["MLA119"] == 120.0


def test_un_listado_de_exactamente_una_pagina_llena_no_pide_de_mas(monkeypatch):
    anuncios = [_anuncio(f"MLA{i}", costo=1.0) for i in range(50)]
    llamadas = _listado(monkeypatch, anuncios)
    ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", [f"MLA{i}" for i in range(50)])
    assert llamadas["paginas"] == [0]                                                           # `paging.total` dice que no hay más


def test_si_una_pagina_falla_se_vuelve_a_consultar_publicacion_por_publicacion(monkeypatch):
    anuncios = [_anuncio(f"MLA{i}", costo=1.0) for i in range(60)]
    por_publicacion = {"MLA5": _Resp(200, {"metrics": {"cost": 77.0}}), "MLA55": _Resp(200, {"metrics": {"cost": 33.0}})}
    llamadas = _listado(monkeypatch, anuncios, falla_en_pagina=50, por_publicacion=por_publicacion)
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA5", "MLA55"])
    assert dict(r) == {"MLA5": 77.0, "MLA55": 33.0} and r.incompleto == 0                       # no se usó el listado a medias: valen los números de cada publicación
    assert sorted(llamadas["individuales"]) == ["MLA5", "MLA55"]
    assert ads._anuncios_cache == {}                                                            # el listado a medias no queda guardado


def test_un_corte_de_conexion_en_el_listado_tampoco_rompe(monkeypatch):
    def cortado(url, **kw):
        if "/ads/search" in url:
            raise ConnectionError("se cortó")
        return _Resp(200, {"metrics": {"cost": 12.0}})
    monkeypatch.setattr(meli_http, "get", cortado)
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert dict(r) == {"MLA1": 12.0} and r.incompleto == 0


def test_un_listado_que_nunca_termina_se_corta_y_usa_el_respaldo(monkeypatch):
    def sin_fin(url, **kw):
        if "/ads/search" in url:
            return _Resp(200, {"results": [_anuncio("MLAX", costo=1.0)] * ads.ANUNCIOS_POR_PAGINA})          # siempre una página llena y sin `paging.total`
        return _Resp(200, {"metrics": {"cost": 8.0}})
    monkeypatch.setattr(meli_http, "get", sin_fin)
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert dict(r) == {"MLA1": 8.0}


def test_los_anuncios_sin_id_se_ignoran_y_el_listado_vacio_es_valido(monkeypatch):
    _listado(monkeypatch, [{"metrics": {"cost": 5}}, _anuncio("MLA1", costo=3.0)])
    r = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert dict(r) == {"MLA1": 3.0}
    ads._costos_cache.clear(); ads._anuncios_cache.clear()
    _listado(monkeypatch, [])
    vacio = ads.obtener_costos_ads_por_item("tok", "A1", "2026-09-01", "2026-09-30", ["MLA1"])
    assert dict(vacio) == {} and vacio.incompleto == 0                                          # una cuenta sin anuncios: sin gasto, no «incompleto»


def test_el_listado_se_guarda_cinco_minutos_por_periodo(monkeypatch):
    llamadas = _listado(monkeypatch, [_anuncio("MLA1", costo=1.0)])
    ads.obtener_anuncios_con_metricas("tok", "A1", "2026-09-01", "2026-09-30")
    ads.obtener_anuncios_con_metricas("tok", "A1", "2026-09-01", "2026-09-30")
    ads.obtener_anuncios_con_metricas("tok", "A1", "2026-09-01", "2026-09-29")                   # otro período: se vuelve a pedir
    ads.obtener_anuncios_con_metricas("tok", "A2", "2026-09-01", "2026-09-30")                   # otro anunciante (otra cuenta): también
    assert llamadas["paginas"] == [0, 0, 0]

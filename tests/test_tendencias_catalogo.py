"""Tendencias: se piden por las categorías específicas donde vende la cuenta (no por la raíz, que trae "slots casino"), mezcladas y cacheadas."""
import cache_db
import tendencias as t
from tests.conftest import CursorFalso


def _tend(*palabras):
    return [{"keyword": p, "url": f"https://x/{p}"} for p in palabras]


def test_mezcla_de_a_una_por_categoria_sin_repetir_y_renumera():
    mezcla = t.mezclar_tendencias([("MLA1", _tend("pantalon", "jean", "cargo")), ("MLA2", _tend("campera", "jean", "bomber", "parka"))])
    assert [x["keyword"] for x in mezcla] == ["pantalon", "campera", "jean", "cargo", "bomber", "parka"]
    assert [x["posicion"] for x in mezcla] == [1, 2, 3, 4, 5, 6]
    assert all(x["relevante"] for x in mezcla)
    assert {x["keyword"]: x["categoria_id"] for x in mezcla}["jean"] == "MLA1"          # el repetido queda con la primera categoría que lo trajo


def test_mezcla_ignora_terminos_vacios_y_mayusculas():
    mezcla = t.mezclar_tendencias([("MLA1", [{"keyword": ""}, {"keyword": "Jean"}]), ("MLA2", [{"keyword": "jean"}])])
    assert [(x["keyword"], x["categoria_id"]) for x in mezcla] == [("jean", "MLA2")]      # el vacío se salta; "Jean" y "jean" son el mismo término


def test_categorias_del_catalogo_pide_las_mas_frecuentes():
    cursor = CursorFalso([("MLA109282", 31), ("MLA109104", 29)])
    assert t.categorias_del_catalogo(cursor, 2) == [("MLA109282", 31), ("MLA109104", 29)]
    sql, params = cursor.consultas[0]
    assert "estado = 'active'" in sql and "ORDER BY 2 DESC" in sql and params == (2,)


def _preparar(monkeypatch, categorias, listas, cache=None):
    llamadas = []
    monkeypatch.setattr(t, "categorias_del_catalogo", lambda cursor, maximo=3: categorias)
    monkeypatch.setattr(t, "obtener_tendencias", lambda token, site, category_id=None, palabras_del_rubro=None: (llamadas.append(category_id), listas.get(category_id, []))[1])
    monkeypatch.setattr(t, "_get_json", lambda url, headers=None, params=None, timeout=10: (200, {"name": "Nombre " + url.rsplit("/", 1)[-1]}))
    guardado = {}
    monkeypatch.setattr(cache_db, "leer", lambda cursor, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None: (True, cache) if cache else (False, None))
    monkeypatch.setattr(cache_db, "guardar", lambda cursor, cuenta, clave, valor, firma="": guardado.update(valor=valor, firma=firma))
    return llamadas, guardado


def test_sin_categorias_devuelve_none_para_usar_la_raiz(monkeypatch):
    llamadas, _ = _preparar(monkeypatch, [], {})
    assert t.obtener_tendencias_del_catalogo("tok", None, 1) is None and llamadas == []


def test_arma_la_lista_con_los_nombres_y_la_guarda_en_cache(monkeypatch):
    llamadas, guardado = _preparar(monkeypatch, [("MLA1", 30), ("MLA2", 10)], {"MLA1": _tend("pantalon", "jean"), "MLA2": _tend("campera")})
    r = t.obtener_tendencias_del_catalogo("tok", None, 1)
    assert llamadas == ["MLA1", "MLA2"]
    assert [x["keyword"] for x in r["lista"]] == ["pantalon", "campera", "jean"]
    assert r["categorias"] == [{"id": "MLA1", "nombre": "Nombre MLA1", "publicaciones": 30}, {"id": "MLA2", "nombre": "Nombre MLA2", "publicaciones": 10}]
    assert guardado["firma"] == "MLA1,MLA2" and guardado["valor"] == r


def test_con_cache_vigente_no_llama_a_mercado_libre(monkeypatch):
    previo = {"lista": _tend("jean"), "categorias": [{"id": "MLA1", "nombre": "Pantalones", "publicaciones": 30}]}
    llamadas, _ = _preparar(monkeypatch, [("MLA1", 30)], {}, cache=previo)
    assert t.obtener_tendencias_del_catalogo("tok", None, 1) == previo and llamadas == []


def test_si_mercado_libre_no_responde_se_recuerda_el_fallo_y_se_usa_la_raiz(monkeypatch):
    llamadas, guardado = _preparar(monkeypatch, [("MLA1", 30)], {})              # la lista de MLA1 viene vacía
    assert t.obtener_tendencias_del_catalogo("tok", None, 1) is None
    assert guardado["valor"] is None and guardado["firma"] == "MLA1"

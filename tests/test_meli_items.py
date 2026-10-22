"""
Multiget de publicaciones: `/items/bulk` con respaldo al viejo `/items?ids=` (Mercado Libre retira el viejo el 25/10/2026).
La respuesta real de `/items/bulk` no se pudo ver desde la PC (sin token de aplicación el API da 403): estas pruebas fijan lo que dice la documentación («Ítems y búsquedas», 10/09/2026) —
`code` pasa a `status_code`, `id` en la raíz, atributos con prefijo `body.`— y que, si Mercado Libre contesta otra cosa, la sincronización sigue andando con el endpoint viejo.
"""
import contextlib
import glob
import json
import os
import re
from urllib.parse import parse_qsl

import pytest

import espia_competencia
import meli_http
import meli_items
import sincronizador

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {"Authorization": "Bearer tok"}


class _Resp:
    def __init__(self, estado, datos=None, texto=None, sin_json=False):
        self.status_code = estado
        self._datos = datos
        self._sin_json = sin_json
        self.text = texto if texto is not None else json.dumps(datos)

    def json(self):
        if self._sin_json:
            raise ValueError("no es JSON")
        return self._datos


def _nuevo(ids, extra=None):
    return [{"id": i, "status_code": 200, "body": {"id": i, "title": f"Titulo {i}", **(extra or {})}} for i in ids]


def _viejo(ids, extra=None):
    return [{"code": 200, "body": {"id": i, "title": f"Titulo {i}", **(extra or {})}} for i in ids]


class _Api:
    """Un `meli_http.get` falso: una función por endpoint, que recibe los ids pedidos y devuelve la respuesta."""

    def __init__(self, bulk=None, viejo=None):
        self.bulk = bulk or (lambda ids: _Resp(200, _nuevo(ids)))
        self.viejo = viejo or (lambda ids: _Resp(200, _viejo(ids)))
        self.llamadas = []

    def get(self, url, headers=None, params=None, timeout=None):
        base, _, consulta = url.partition("?")
        assert params is None and "%2C" not in consulta, f"la consulta va escrita a mano, con las comas sin codificar: {url}"
        parametros = dict(parse_qsl(consulta, keep_blank_values=True))
        self.llamadas.append((base, parametros))
        ids = parametros["ids"].split(",")
        return (self.bulk if base == meli_items.URL_BULK else self.viejo)(ids)

    def urls(self):
        return [u for u, _ in self.llamadas]


@pytest.fixture(autouse=True)
def _estado_limpio(monkeypatch):
    meli_items._ESTADO["bulk_saltear_hasta"] = 0.0
    meli_items._ESTADO["avisado"].clear()
    yield
    meli_items._ESTADO["bulk_saltear_hasta"] = 0.0
    meli_items._ESTADO["avisado"].clear()


def _instalar(monkeypatch, api):
    monkeypatch.setattr(meli_http, "get", api.get)
    return api


def _ids(n):
    return [f"MLA{1000 + i}" for i in range(n)]


def test_usa_bulk_con_los_atributos_con_prefijo_body_y_normaliza(monkeypatch):
    api = _instalar(monkeypatch, _Api())
    elementos, fallos = meli_items.traer_items(["MLA1", "MLA2"], HEADERS, atributos=("id", "title"))
    assert fallos == []
    # `id` y `status_code` se piden aparte: con `body.` solo, el endpoint real manda cada elemento como {body: {...}} y una publicación inexistente como {} (verificado 2026-10-21)
    assert api.llamadas == [(meli_items.URL_BULK, {"ids": "MLA1,MLA2", "attributes": "id,status_code,body.id,body.title"})]
    assert elementos == [{"id": "MLA1", "status_code": 200, "body": {"id": "MLA1", "title": "Titulo MLA1"}, "error": None},
                         {"id": "MLA2", "status_code": 200, "body": {"id": "MLA2", "title": "Titulo MLA2"}, "error": None}]


def test_acepta_la_forma_vieja_de_los_elementos_aunque_conteste_bulk(monkeypatch):
    """Si `/items/bulk` todavía devolviera `code` en vez de `status_code`, se entiende igual."""
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, _viejo(ids))))
    elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
    assert fallos == [] and api.urls() == [meli_items.URL_BULK]
    assert elementos == [{"id": "MLA1", "status_code": 200, "body": {"id": "MLA1", "title": "Titulo MLA1"}, "error": None}]


def test_sin_atributos_no_manda_el_parametro(monkeypatch):
    api = _instalar(monkeypatch, _Api())
    meli_items.traer_items(["MLA1"], HEADERS)
    assert "attributes" not in api.llamadas[0][1]


def test_parte_la_lista_de_a_20_sin_repetir_ni_perder_el_orden(monkeypatch):
    api = _instalar(monkeypatch, _Api())
    ids = _ids(45)
    elementos, fallos = meli_items.traer_items(ids + ids[:3] + [None, ""], HEADERS)
    assert fallos == []
    assert [len(p["ids"].split(",")) for _, p in api.llamadas] == [20, 20, 5]
    assert [e["id"] for e in elementos] == ids


def test_sin_ids_no_llama_a_nadie(monkeypatch):
    api = _instalar(monkeypatch, _Api())
    assert meli_items.traer_items([], HEADERS) == ([], [])
    assert meli_items.traer_items(None, HEADERS) == ([], [])
    assert api.llamadas == []


def test_si_bulk_no_existe_vuelve_al_viejo_con_los_atributos_sin_prefijo_y_no_insiste(monkeypatch):
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(404, {"message": "not found"})))
    elementos, fallos = meli_items.traer_items(_ids(25), HEADERS, atributos=("id", "title"))
    assert fallos == [] and len(elementos) == 25
    # lote 1: bulk (404) y viejo; lote 2: directo al viejo (no se vuelve a pedir un endpoint que acaba de decir «no existe»)
    assert api.urls() == [meli_items.URL_BULK, meli_items.URL_VIEJA, meli_items.URL_VIEJA]
    assert api.llamadas[1][1]["attributes"] == "id,title"


def test_pasada_la_espera_vuelve_a_probar_bulk(monkeypatch):
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(405, None, "no")))
    meli_items.traer_items(["MLA1"], HEADERS)
    meli_items._ESTADO["bulk_saltear_hasta"] = 0.0                      # pasó la media hora
    api.bulk = lambda ids: _Resp(200, _nuevo(ids))
    elementos, _ = meli_items.traer_items(["MLA2"], HEADERS)
    assert api.urls()[-1] == meli_items.URL_BULK and elementos[0]["id"] == "MLA2"


def test_un_400_de_bulk_prueba_el_viejo_pero_no_descarta_bulk(monkeypatch):
    """Un 400 puede ser el formato del pedido nuevo, no que el endpoint no exista: el lote siguiente vuelve a intentar bulk."""
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(400, {"message": "bad attributes"})))
    elementos, fallos = meli_items.traer_items(_ids(25), HEADERS, atributos=("id",))
    assert fallos == [] and len(elementos) == 25
    assert api.urls() == [meli_items.URL_BULK, meli_items.URL_VIEJA, meli_items.URL_BULK, meli_items.URL_VIEJA]


@pytest.mark.parametrize("cuerpo", [{"results": []}, "texto", None, [1, 2], [{"id": "MLA1"}], [{"status_code": True}]])
def test_si_bulk_contesta_200_con_algo_que_no_es_una_lista_de_publicaciones_se_usa_el_viejo(monkeypatch, cuerpo):
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, cuerpo)))
    elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
    assert fallos == [] and api.urls() == [meli_items.URL_BULK, meli_items.URL_VIEJA]
    assert elementos[0]["id"] == "MLA1"


# Formas REALES de /items/bulk, tal como las devolvió Mercado Libre el 2026-10-21 (publicaciones propias y un id inexistente)
def test_un_elemento_que_mercado_libre_no_encontro_trae_error_y_no_body(monkeypatch):
    datos = [{"id": "MLA1", "status_code": 200, "body": {"id": "MLA1"}}, {"id": "MLA2", "status_code": 404, "error": {"message": "Item not found"}}]
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, datos)))
    elementos, fallos = meli_items.traer_items(["MLA1", "MLA2"], HEADERS)
    assert fallos == [] and api.urls() == [meli_items.URL_BULK]
    assert elementos[1] == {"id": "MLA2", "status_code": 404, "body": None, "error": {"message": "Item not found"}}


def test_un_elemento_filtrado_que_llega_solo_con_body_se_entiende_como_exito(monkeypatch):
    """`attributes=body.id,body.title` (sin pedir la raíz) devuelve [{body: {...}}]: hay cuerpo, salió bien."""
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, [{"body": {"id": "MLA1", "title": "A"}}, {}])))
    elementos, fallos = meli_items.traer_items(["MLA1", "MLA2"], HEADERS)
    assert fallos == [] and api.urls() == [meli_items.URL_BULK]
    assert [(e["id"], e["status_code"]) for e in elementos] == [("MLA1", 200), (None, 0)]              # el inexistente llega como {}: sin estado, no se confunde con un éxito


def test_si_ningun_elemento_dice_nada_se_prueba_el_viejo(monkeypatch):
    """`attributes=id,title` sin prefijo llega solo con `id` (o todo `{}`): no se puede usar, y con el viejo sí."""
    for cuerpo in ([{"id": "MLA1"}], [{}, {}]):
        api = _instalar(monkeypatch, _Api(bulk=lambda ids, c=cuerpo: _Resp(200, c)))
        elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
        assert fallos == [] and api.urls() == [meli_items.URL_BULK, meli_items.URL_VIEJA]
        assert elementos[0]["status_code"] == 200


def test_si_bulk_contesta_200_sin_json_se_usa_el_viejo(monkeypatch):
    api = _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, sin_json=True, texto="<html>")))
    elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
    assert fallos == [] and len(elementos) == 1 and api.urls() == [meli_items.URL_BULK, meli_items.URL_VIEJA]


@pytest.mark.parametrize("estado", [401, 403, 429, 500, 503])
def test_un_rechazo_que_el_viejo_repetiria_no_se_reintenta_y_no_corta_los_otros_lotes(monkeypatch, estado):
    def bulk(ids):
        return _Resp(estado, {"message": "no"}) if ids[0] == "MLA1020" else _Resp(200, _nuevo(ids))

    api = _instalar(monkeypatch, _Api(bulk=bulk))
    elementos, fallos = meli_items.traer_items(_ids(45), HEADERS)
    assert len(elementos) == 25                                         # el 1.º y el 3.er lote llegaron
    assert [(cantidad, e) for cantidad, e, _ in fallos] == [(20, estado)]
    assert meli_items.URL_VIEJA not in api.urls()


def test_si_tambien_falla_el_viejo_el_lote_figura_como_fallo(monkeypatch):
    _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(404, None, "x"), viejo=lambda ids: _Resp(400, {"message": "only allows 20 elements"})))
    elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
    assert elementos == [] and fallos[0][:2] == (1, 400) and "only allows" in fallos[0][2]


def test_el_viejo_que_contesta_algo_que_no_es_una_lista_figura_como_fallo(monkeypatch):
    _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(404, None, "x"), viejo=lambda ids: _Resp(200, {"mensaje": "otra cosa"})))
    elementos, fallos = meli_items.traer_items(["MLA1"], HEADERS)
    assert elementos == [] and fallos[0][0] == 1 and fallos[0][1] == 200 and "no es una lista" in fallos[0][2]


def test_una_publicacion_que_mercado_libre_no_encontro_pasa_con_su_estado(monkeypatch):
    """Cada elemento trae su propio estado: la sincronización se queda con los 200 y salta el resto."""
    datos = [{"id": "MLA1", "status_code": 200, "body": {"id": "MLA1"}}, {"id": "MLA2", "status_code": 404, "body": {"message": "Item not found"}}]
    _instalar(monkeypatch, _Api(bulk=lambda ids: _Resp(200, datos)))
    elementos, fallos = meli_items.traer_items(["MLA1", "MLA2"], HEADERS)
    assert fallos == [] and [(e["id"], e["status_code"]) for e in elementos] == [("MLA1", 200), ("MLA2", 404)]


def test_un_error_de_conexion_se_propaga_como_antes(monkeypatch):
    def cae(*a, **k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(meli_http, "get", cae)
    with pytest.raises(ConnectionError):
        meli_items.traer_items(["MLA1"], HEADERS)


# ── el sincronizador de catálogo con el endpoint nuevo ────────────────────────────────────────────────

class _Cursor:
    def __init__(self, sql):
        self.sql = sql

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return (777,)


def _correr_catalogo(monkeypatch, api, ids):
    escritos, sql = [], []

    @contextlib.contextmanager
    def conexion(*a, **k):
        yield type("C", (), {"cursor": lambda s: _Cursor(sql)})()

    monkeypatch.setattr(sincronizador.db, "conexion_usuario", conexion)
    monkeypatch.setattr(sincronizador.token_manager, "asegurar_token_valido", lambda c: "tok")
    monkeypatch.setattr(sincronizador.cache_db, "leer", lambda *a, **k: (False, None))
    monkeypatch.setattr(sincronizador.cache_db, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(sincronizador, "listar_ids_publicaciones", lambda *a, **k: ids)
    monkeypatch.setattr(sincronizador, "_contexto_de_variantes", lambda *a, **k: {})
    monkeypatch.setattr(sincronizador, "_escribir_item_en_db", lambda cuenta_id, datos, cursor, contexto=None: escritos.append(datos["id_item"]))
    monkeypatch.setattr(meli_http, "get", api.get)
    sincronizador.sincronizar_catalogo(5, 9)
    return escritos, sql


def test_el_sync_de_catalogo_guarda_todo_con_la_respuesta_nueva_de_bulk(monkeypatch):
    ids = _ids(45)
    api = _Api()
    escritos, sql = _correr_catalogo(monkeypatch, api, ids)
    assert escritos == ids
    assert set(api.urls()) == {meli_items.URL_BULK}
    assert any("ultima_sincronizacion = now()" in s for s in sql)


def test_el_sync_de_catalogo_sigue_andando_si_bulk_no_existe(monkeypatch):
    ids = _ids(25)
    api = _Api(bulk=lambda i: _Resp(404, None, "no"))
    escritos, _ = _correr_catalogo(monkeypatch, api, ids)
    assert escritos == ids


def test_el_sync_de_catalogo_salta_las_publicaciones_que_no_dieron_200_y_avisa_del_lote_caido(monkeypatch, capsys):
    ids = _ids(45)

    def bulk(pedidos):
        if pedidos[0] == "MLA1020":
            return _Resp(429, {"message": "too many"})
        return _Resp(200, [{"id": i, "status_code": 404 if i == "MLA1001" else 200, "body": {"id": i}} for i in pedidos])

    escritos, _ = _correr_catalogo(monkeypatch, _Api(bulk=bulk), ids)
    assert escritos == [i for i in ids if i != "MLA1001" and not (1020 <= int(i[3:]) < 1040)]
    assert "rechazó un lote de 20 ítems (429)" in capsys.readouterr().out


# ── sugerencias de la Competencia (mandaba hasta 40 ids de una vez: Mercado Libre acepta 20) ───────────

def test_las_sugerencias_de_competencia_parten_en_lotes_y_suman_todos(monkeypatch):
    ids = _ids(40)

    def bulk(pedidos):
        return _Resp(200, [{"id": i, "status_code": 200, "body": {"id": i, "title": f"Modelo {i}", "catalog_product_id": "MLA55555" if int(i[3:]) % 2 else "MLA66666"}} for i in pedidos])

    api = _instalar(monkeypatch, _Api(bulk=bulk))
    sugerencias = espia_competencia.sugerir_productos_propios("tok", ids, set())
    assert [len(p["ids"].split(",")) for _, p in api.llamadas] == [20, 20]
    assert api.llamadas[0][1]["attributes"] == "id,status_code,body.id,body.title,body.catalog_product_id"
    assert {s["id_producto"]: s["publicaciones_propias"] for s in sugerencias} == {"MLA55555": 20, "MLA66666": 20}


def test_las_sugerencias_ignoran_lo_que_ya_se_sigue_y_los_errores(monkeypatch):
    def bulk(pedidos):
        return _Resp(200, [{"id": "MLA1", "status_code": 200, "body": {"id": "MLA1", "title": "A", "catalog_product_id": "MLA55555"}},
                           {"id": "MLA2", "status_code": 404, "body": {"message": "no"}}])

    _instalar(monkeypatch, _Api(bulk=bulk))
    assert espia_competencia.sugerir_productos_propios("tok", ["MLA1", "MLA2"], {"MLA55555"}) == []


def test_las_sugerencias_no_rompen_si_mercado_libre_no_responde(monkeypatch):
    def cae(*a, **k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(meli_http, "get", cae)
    assert espia_competencia.sugerir_productos_propios("tok", ["MLA1"], set()) == []
    assert espia_competencia.sugerir_productos_propios("tok", [], set()) == []


# ── guarda: nadie vuelve a llamar al multiget viejo por su cuenta ─────────────────────────────────────

def test_ningun_modulo_llama_al_multiget_viejo_por_fuera_de_meli_items():
    """`/items?ids=` y `/users?ids=` dejan de existir el 25/10/2026: todo multiget pasa por `meli_items` (que sabe de las dos formas)."""
    patron = re.compile(r'mercadolibre\.com/(?:items|users)(?:\?ids|["\'][^)\n]{0,160}["\']ids["\'])')
    usan = []
    for patron_glob in ("*.py", "auth/*.py", "tasks/*.py"):
        for ruta in glob.glob(os.path.join(RAIZ, patron_glob)):
            rel = os.path.relpath(ruta, RAIZ)
            if rel in ("meli_items.py", "sondeo_meli.py"):
                continue
            if patron.search(open(ruta, encoding="utf-8").read()):
                usan.append(rel)
    assert not usan, f"Llaman al multiget viejo sin pasar por meli_items: {usan}"


def test_el_sincronizador_y_la_competencia_usan_meli_items():
    for rel in ("sincronizador.py", "espia_competencia.py"):
        assert "meli_items.traer_items(" in open(os.path.join(RAIZ, rel), encoding="utf-8").read(), rel

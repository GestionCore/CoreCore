"""
Publicaciones «zombie» (activas, sin visitas ni ventas en 60 días). Detectarlas costaba 79 llamadas a Mercado Libre (2,2 s, el 35 % de la pantalla Día a día) cada 15 minutos y por proceso.
Ahora las visitas de cada publicación se guardan 6 h en cache_db (compartidas entre procesos, cada dato con su propia hora) y solo se pide lo que falta, venció o falló.
Y un fallo de Mercado Libre ya no cuenta como «0 visitas»: acusaba de zombie a una publicación que sí tenía visitas.
"""
import embudo_conversion as emb
import meli_http


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo or {}

    def json(self):
        return self._cuerpo


class _Cursor:
    """Responde las tres consultas de detectar_publicaciones_zombie y simula la tabla cache_valores en memoria."""

    def __init__(self, activos, con_venta, guardado=None):
        self.activos, self.con_venta, self.cache = activos, con_venta, guardado
        self._ultimo = None

    def execute(self, sql, params=None):
        self._ultimo = sql

    def fetchall(self):
        if "FROM productos_padre" in self._ultimo:
            return self.activos
        if "FROM ventas" in self._ultimo:
            return [(i,) for i in self.con_venta]
        return []


def _con_cache_en_memoria(monkeypatch, cursor, inicial=None):
    estado = {"valor": inicial, "firma": "60", "guardados": 0}

    def leer(cur, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None):
        return (True, estado["valor"]) if estado["valor"] is not None and estado["firma"] == firma else (False, None)

    def guardar(cur, cuenta, clave, valor, firma=""):
        estado["valor"], estado["firma"] = valor, firma
        estado["guardados"] += 1
    monkeypatch.setattr(emb.cache_db, "leer", leer)
    monkeypatch.setattr(emb.cache_db, "guardar", guardar)
    return estado


def _visitas_de_meli(monkeypatch, tabla):
    """{id: visitas | _Resp de error}; devuelve la lista de ids pedidos."""
    pedidos = []

    def falso(url, **kw):
        item = url.split("/items/")[1].split("/")[0]
        pedidos.append(item)
        r = tabla[item]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, _Resp) else _Resp(200, {"total_visits": r})
    monkeypatch.setattr(meli_http, "get", falso)
    return pedidos


ACTIVOS = [("MLA1", "Campera", "t1"), ("MLA2", "Termo", "t2"), ("MLA3", "Gorra", "t3")]


def test_sin_cache_se_piden_todas_y_se_guardan(monkeypatch):
    estado = _con_cache_en_memoria(monkeypatch, None)
    pedidos = _visitas_de_meli(monkeypatch, {"MLA1": 0, "MLA2": 15, "MLA3": 0})
    zombies = emb.detectar_publicaciones_zombie({}, 1, _Cursor(ACTIVOS, con_venta=["MLA3"]))
    assert sorted(pedidos) == ["MLA1", "MLA2", "MLA3"]
    assert [z["id_meli"] for z in zombies] == ["MLA1"]                  # MLA2 tiene visitas; MLA3 no tiene pero vendió
    assert set(estado["valor"]) == {"MLA1", "MLA2", "MLA3"} and estado["guardados"] == 1


def test_con_cache_vigente_no_se_llama_a_mercado_libre(monkeypatch):
    import time
    ahora = time.time()
    _con_cache_en_memoria(monkeypatch, None, inicial={"MLA1": [0, ahora - 60], "MLA2": [15, ahora - 60], "MLA3": [0, ahora - 60]})
    pedidos = _visitas_de_meli(monkeypatch, {})
    zombies = emb.detectar_publicaciones_zombie({}, 1, _Cursor(ACTIVOS, con_venta=[]))
    assert pedidos == [] and [z["id_meli"] for z in zombies] == ["MLA1", "MLA3"]


def test_lo_que_se_vendio_o_se_pauso_se_lee_siempre_de_la_base_no_de_la_cache(monkeypatch):
    import time
    ahora = time.time()
    _con_cache_en_memoria(monkeypatch, None, inicial={"MLA1": [0, ahora], "MLA2": [0, ahora], "MLA3": [0, ahora]})
    _visitas_de_meli(monkeypatch, {})
    # MLA1 vendió después de guardada la caché y MLA2 se pausó (ya no figura entre las activas): la lista se corrige sin llamar a nadie
    zombies = emb.detectar_publicaciones_zombie({}, 1, _Cursor([a for a in ACTIVOS if a[0] != "MLA2"], con_venta=["MLA1"]))
    assert [z["id_meli"] for z in zombies] == ["MLA3"]


def test_solo_se_piden_las_nuevas_las_vencidas_y_las_que_fallaron(monkeypatch):
    import time
    ahora = time.time()
    estado = _con_cache_en_memoria(monkeypatch, None, inicial={
        "MLA1": [0, ahora - 60],                                         # vigente
        "MLA2": [15, ahora - (emb.TTL_VISITA_SEGUNDOS + 10)],            # venció
        "MLA3": [None, ahora - 60],                                      # quedó guardada sin dato (formato viejo o corrupto): se vuelve a pedir
    })
    pedidos = _visitas_de_meli(monkeypatch, {"MLA2": 0, "MLA3": 4})
    emb.detectar_publicaciones_zombie({}, 1, _Cursor(ACTIVOS, con_venta=[]))
    assert sorted(pedidos) == ["MLA2", "MLA3"]
    assert estado["valor"]["MLA1"][1] < ahora - 30                       # la hora del dato vigente NO se renovó por haber pedido otros
    assert estado["valor"]["MLA2"][0] == 0 and estado["valor"]["MLA3"][0] == 4


def test_un_error_de_mercado_libre_no_vuelve_zombie_a_nadie_ni_se_guarda(monkeypatch):
    estado = _con_cache_en_memoria(monkeypatch, None)
    _visitas_de_meli(monkeypatch, {"MLA1": _Resp(429), "MLA2": ConnectionError("se cortó"), "MLA3": 0})
    zombies = emb.detectar_publicaciones_zombie({}, 1, _Cursor(ACTIVOS, con_venta=[]))
    assert [z["id_meli"] for z in zombies] == ["MLA3"]                   # MLA1 y MLA2: «no sabemos», no «0 visitas»
    assert set(estado["valor"]) == {"MLA3"}                              # y lo que falló no queda guardado: la próxima vez se reintenta


def test_otra_ventana_de_dias_no_reutiliza_la_cache(monkeypatch):
    import time
    _con_cache_en_memoria(monkeypatch, None, inicial={"MLA1": [0, time.time()]})
    pedidos = _visitas_de_meli(monkeypatch, {"MLA1": 5, "MLA2": 5, "MLA3": 5})
    emb.detectar_publicaciones_zombie({}, 1, _Cursor(ACTIVOS, con_venta=[]), dias=30)
    assert sorted(pedidos) == ["MLA1", "MLA2", "MLA3"]


def test_el_embudo_tolera_visitas_desconocidas(monkeypatch):
    """calcular_embudo_conversion llama a obtener_visitas_items para las publicaciones sin dato guardado: un None no debe romper las sumas."""
    _visitas_de_meli(monkeypatch, {"MLA1": _Resp(500), "MLA2": 10})
    r = emb.obtener_visitas_items({}, ["MLA1", "MLA2"], "2026-09-01", "2026-09-30")
    assert r == {"MLA1": None, "MLA2": 10}
    assert sum((r.get(i, 0) or 0) for i in ("MLA1", "MLA2")) == 10

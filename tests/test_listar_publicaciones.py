import sincronizador as s


class Resp:
    def __init__(self, cuerpo, codigo=200):
        self._c, self.status_code = cuerpo, codigo

    def json(self):
        return self._c


class MeLiFalso:
    """Simula /users/{id}/items/search con offset (tope 1000) y con scan + scroll_id."""

    def __init__(self, total, scan_falla=False):
        self.todos = [f"MLA{i}" for i in range(total)]
        self.llamadas = []
        self.scan_falla = scan_falla

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.llamadas.append(dict(params))
        if params.get("search_type") == "scan":
            if self.scan_falla:
                return Resp({}, 400)
            desde = int(params["scroll_id"]) if params.get("scroll_id") else 0
            pagina = self.todos[desde:desde + params["limit"]]
            return Resp({"results": pagina, "scroll_id": str(desde + len(pagina)), "paging": {"total": len(self.todos)}})
        offset = params["offset"]
        if offset >= 1000:
            return Resp({"error": "offset"}, 400)
        return Resp({"results": self.todos[offset:offset + params["limit"]], "paging": {"total": len(self.todos)}})


def test_hasta_mil_publicaciones_se_pagina_por_offset_sin_scan():
    meli = MeLiFalso(250)
    ids = s.listar_ids_publicaciones(1, {}, 1, get=meli)
    assert ids == meli.todos
    assert not any(c.get("search_type") for c in meli.llamadas)


def test_con_mas_de_mil_se_usa_scan_y_no_se_pierde_ninguna():
    meli = MeLiFalso(2350)
    ids = s.listar_ids_publicaciones(1, {}, 1, get=meli)
    assert len(ids) == 2350 and ids == meli.todos
    assert any(c.get("search_type") == "scan" for c in meli.llamadas)


def test_si_el_scan_falla_quedan_al_menos_las_primeras_mil():
    meli = MeLiFalso(1500, scan_falla=True)
    assert s.listar_ids_publicaciones(1, {}, 1, get=meli) == meli.todos[:1000]


def test_exactamente_mil_no_necesita_scan():
    meli = MeLiFalso(1000)
    assert s.listar_ids_publicaciones(1, {}, 1, get=meli) == meli.todos
    assert not any(c.get("search_type") for c in meli.llamadas)


def test_sin_publicaciones_devuelve_vacio():
    assert s.listar_ids_publicaciones(1, {}, 1, get=MeLiFalso(0)) == []

"""Stock de convivencia (propio + FULL): se vuelve a pedir a MeLi solo si la publicación se movió o pasó la vigencia. Sin base ni red."""
import sincronizador as s

AHORA = 1_000_000.0
VIGENCIA = s.VIGENCIA_CONVIVENCIA_SEGUNDOS


def _p(i, firma="f1"):
    return (i, f"UP{i}", f"MLA{i}", firma)


def test_la_primera_vez_siempre_se_consulta():
    a_consultar, a_conservar = s.decidir_convivencia([_p(0), _p(1)], {}, AHORA)
    assert len(a_consultar) == 2 and not a_conservar


def test_sin_cambios_y_dentro_de_la_vigencia_se_conserva():
    previo = {"MLA0": ["f1", AHORA - 60], "MLA1": ["f1", AHORA - 60]}
    a_consultar, a_conservar = s.decidir_convivencia([_p(0), _p(1)], previo, AHORA)
    assert not a_consultar and len(a_conservar) == 2


def test_si_la_publicacion_se_movio_se_vuelve_a_consultar():
    previo = {"MLA0": ["f1", AHORA - 60], "MLA1": ["f1", AHORA - 60]}
    a_consultar, a_conservar = s.decidir_convivencia([_p(0, "f2"), _p(1)], previo, AHORA)
    assert [x[2] for x in a_consultar] == ["MLA0"] and [x[2] for x in a_conservar] == ["MLA1"]


def test_vencida_la_vigencia_se_consulta_aunque_no_se_haya_movido():
    previo = {"MLA0": ["f1", AHORA - VIGENCIA - 1], "MLA1": ["f1", AHORA - VIGENCIA + 60]}
    a_consultar, a_conservar = s.decidir_convivencia([_p(0), _p(1)], previo, AHORA)
    assert [x[2] for x in a_consultar] == ["MLA0"] and [x[2] for x in a_conservar] == ["MLA1"]


def test_la_firma_incluye_lo_que_cambia_con_una_venta_o_una_reposicion():
    base = {"last_updated": "2026-10-02T10:00", "sold_quantity": 5, "available_quantity": 36}
    assert s.firma_de_movimiento(base) == s.firma_de_movimiento(dict(base))
    for campo, valor in (("last_updated", "2026-10-02T11:00"), ("sold_quantity", 6), ("available_quantity", 35)):
        assert s.firma_de_movimiento({**base, campo: valor}) != s.firma_de_movimiento(base)


# ── Escritura: conservar el reparto guardado en lugar de pisarlo ──────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, stock_guardado):
        self.stock_guardado, self.escrituras, self._ultima = stock_guardado, [], ""

    def execute(self, sql, params=None):
        self._ultima = " ".join(sql.split())
        if self._ultima.startswith("INSERT INTO productos_variantes"):
            self.escrituras.append(params)

    def fetchone(self):
        if "FROM productos_padre WHERE" in self._ultima:
            return None
        if "RETURNING id" in self._ultima:
            return (7,)
        if "FROM productos_variantes" in self._ultima:
            return self.stock_guardado
        return None


def _item(**extra):
    p = {"id": "MLA1", "title": "Campera", "price": 1000, "status": "active", "shipping": {"logistic_type": "fulfillment", "tags": ["self_service_in"]},
         "available_quantity": 36, "variations": [], "attributes": [], "user_product_id": "UP1"}
    return {"id_item": "MLA1", "detalle": p, "precio_original": None, "recibis_estimado": None, **extra}


def test_sin_cambios_se_conserva_el_reparto_propio_y_full_ya_guardado():
    cursor = _Cursor((12, 36))
    s._escribir_item_en_db(1, _item(stock_convivencia=None, convivencia_sin_cambios=True), cursor)
    assert cursor.escrituras[0][-2:] == (12, 36)


def test_con_stock_consultado_se_usa_el_nuevo_reparto():
    cursor = _Cursor((12, 36))
    s._escribir_item_en_db(1, _item(stock_convivencia=(5, 40)), cursor)
    assert cursor.escrituras[0][-2:] == (5, 40)

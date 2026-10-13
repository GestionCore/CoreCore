"""
El sincronizador guarda la variante de cada publicación por sus atributos (variantes.py) y deja de leer el talle del título. Sin base ni red: un cursor falso anota lo que se escribe.
"""
import json

import mercado_categorias
import sincronizador as s

CATEGORIA = "MLA1055"
DIMENSIONES = {CATEGORIA: {"variacion": ["COLOR"], "ocultos": ["GTIN", "SELLER_SKU"], "al_dia": True}}


def _a(id_, valor):
    return {"id": id_, "name": id_.title(), "value_id": "1", "value_name": valor}


def _iphone(item_id, titulo, color, memoria, familia="F1"):
    return {"id_item": item_id, "precio_original": None, "recibis_estimado": None, "stock_convivencia": None, "detalle": {
        "id": item_id, "title": titulo, "price": 1000, "status": "active", "category_id": CATEGORIA, "domain_id": "MLA-CELLPHONES", "family_id": familia,
        "shipping": {"logistic_type": "cross_docking"}, "available_quantity": 4, "variations": [],
        "attributes": [_a("BRAND", "Apple"), _a("MODEL", "iPhone 15"), _a("COLOR", color), _a("MAIN_COLOR", color), _a("INTERNAL_MEMORY", memoria), _a("GTIN", item_id), _a("SELLER_SKU", item_id)]}}


class _Cursor:
    def __init__(self, hermanas=()):
        self.padres, self.variantes, self._ultima, self.hermanas = [], [], "", list(hermanas)

    def execute(self, sql, params=None):
        self._ultima = " ".join(sql.split())
        if self._ultima.startswith("INSERT INTO productos_padre"):
            self.padres.append(params)
        elif self._ultima.startswith("INSERT INTO productos_variantes"):
            self.variantes.append(params)

    def fetchone(self):
        if "FROM productos_padre WHERE" in self._ultima:
            return None
        return (7,) if "RETURNING id" in self._ultima else None

    def fetchall(self):
        return [(h,) for h in self.hermanas] if "atributos_clave FROM productos_padre" in self._ultima else []


def _escribir(items, cursor, monkeypatch):
    monkeypatch.setattr(mercado_categorias, "asegurar_dimensiones", lambda cur, ids, headers: DIMENSIONES)
    contexto = s._contexto_de_variantes(cursor, items, headers={})
    for datos in items:
        s._escribir_item_en_db(1, datos, cursor, contexto)


def test_tres_celulares_de_una_familia_quedan_con_su_memoria_y_su_color_aunque_el_titulo_termine_en_numero(monkeypatch):
    items = [_iphone("MLA1", "Apple iPhone 15", "Rosa", "128 GB"), _iphone("MLA2", "Apple iPhone 15", "Rosa", "256 GB"), _iphone("MLA3", "Apple iPhone 14", "Azul", "128 GB")]
    cursor = _Cursor()
    _escribir(items, cursor, monkeypatch)
    etiquetas = [v[6] for v in cursor.variantes]
    assert etiquetas == ["128 GB / Rosa", "256 GB / Rosa", "128 GB / Azul"]
    assert [(v[3], v[4]) for v in cursor.variantes] == [("Único", "Rosa"), ("Único", "Rosa"), ("Único", "Azul")]      # el «15» del título ya no es un talle
    atributos = json.loads(cursor.variantes[0][5])
    assert [(a["id"], a["value_name"]) for a in atributos] == [("INTERNAL_MEMORY", "128 GB"), ("COLOR", "Rosa")]


def test_la_publicacion_guarda_su_dominio_y_sus_atributos_visibles_sin_datos_tecnicos(monkeypatch):
    cursor = _Cursor()
    _escribir([_iphone("MLA1", "Apple iPhone 15", "Rosa", "128 GB")], cursor, monkeypatch)
    dominio, atributos_clave = cursor.padres[0][-2:]
    assert dominio == "MLA-CELLPHONES"
    assert json.loads(atributos_clave) == {"BRAND": "Apple", "MODEL": "iPhone 15", "COLOR": "Rosa", "INTERNAL_MEMORY": "128 GB"}     # sin GTIN, SKU ni MAIN_COLOR


def test_una_publicacion_con_variaciones_clasicas_usa_las_de_cada_variacion(monkeypatch):
    item = _iphone("MLA9", "Campera", "Negro", "128 GB", familia=None)
    item["detalle"]["variations"] = [
        {"id": 11, "available_quantity": 2, "attribute_combinations": [{"id": "COLOR", "name": "Color", "value_name": "Negro"}, {"id": "SIZE", "name": "Talle", "value_name": "M"}]},
        {"id": 12, "available_quantity": 3, "attribute_combinations": [{"id": "COLOR", "name": "Color", "value_name": "Negro"}, {"id": "SIZE", "name": "Talle", "value_name": "L"}]},
    ]
    cursor = _Cursor()
    _escribir([item], cursor, monkeypatch)
    assert [(v[1], v[3], v[4], v[6]) for v in cursor.variantes] == [("11", "M", "Negro", "M / Negro"), ("12", "L", "Negro", "L / Negro")]


def test_una_publicacion_sin_atributos_que_la_distingan_queda_como_unica(monkeypatch):
    item = _iphone("MLA5", "Termo Acero 1 L", "x", "x", familia=None)
    item["detalle"]["attributes"] = [_a("BRAND", "Stanley")]
    cursor = _Cursor()
    _escribir([item], cursor, monkeypatch)
    assert cursor.variantes[0][1] == "MLA5_unica" and cursor.variantes[0][3:7] == ("Único", "Único", "[]", "Única")


def test_la_notificacion_de_una_sola_publicacion_compara_con_las_hermanas_ya_guardadas(monkeypatch):
    """El aviso de Mercado Libre trae UNA publicación: sus hermanas salen de lo que se guardó antes (productos_padre.atributos_clave)."""
    monkeypatch.setattr(mercado_categorias, "asegurar_dimensiones", lambda cur, ids, headers: DIMENSIONES)
    hermana = {"BRAND": "Apple", "MODEL": "iPhone 15", "COLOR": "Rosa", "INTERNAL_MEMORY": "256 GB"}
    cursor = _Cursor(hermanas=[hermana, {}])                                    # una hermana sin atributos guardados todavía no cuenta
    item = _iphone("MLA1", "Apple iPhone 15", "Rosa", "128 GB")
    contexto = s._contexto_de_un_item(cursor, 1, item["detalle"], headers={})
    assert len(contexto["familias"]["F1"]) == 2
    s._escribir_item_en_db(1, item, cursor, contexto)
    assert cursor.variantes[0][6] == "128 GB"                                   # el color es igual en las dos: lo que la distingue es la memoria


def test_sin_contexto_igual_se_escribe_con_los_atributos_de_la_propia_publicacion():
    cursor = _Cursor()
    item = _iphone("MLA1", "Apple iPhone 15", "Rosa", "128 GB", familia=None)
    s._escribir_item_en_db(1, item, cursor)
    assert cursor.variantes[0][3:5] == ("Único", "Rosa") and cursor.variantes[0][6] == "Única"          # sin categoría conocida no hay dimensiones: nada que mostrar

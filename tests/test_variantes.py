"""
Variantes por atributos (variantes.py): lo que distingue a una publicación de otra, leído de los atributos de Mercado Libre y nunca del título. Los casos son los reales del sondeo
(docs/SONDEO_FASE0.md): un iPhone con memoria y color, una pintura por litros, ropa con talle «Único», una publicación con variaciones clásicas.
"""
import pytest

import variantes as v


def _a(id_, valor, nombre=None, **extra):
    return {"id": id_, "name": nombre or id_.title(), "value_id": "1", "value_name": valor, **extra}


def _iphone(color, memoria, gtin="750", sku="X"):
    return [_a("BRAND", "Apple", "Marca"), _a("MODEL", "iPhone 15", "Modelo"), _a("COLOR", color, "Color"), _a("MAIN_COLOR", color, "Color principal"),
            _a("INTERNAL_MEMORY", memoria, "Memoria interna"), _a("RAM", "6 GB", "Memoria RAM"), _a("GTIN", gtin), _a("SELLER_SKU", sku), _a("PACKAGE_WEIGHT", "400 g"),
            _a("IS_DUAL_SIM", "Sí"), _a("ITEM_CONDITION", "Nuevo")]


OCULTOS_CELULARES = ["GTIN", "SELLER_SKU", "PACKAGE_WEIGHT"]


# ── Qué es útil y qué es técnico ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor", [None, "", "  ", "Único", "UNICO", "única", "Talle único", "N/A", "No aplica", "Sin especificar"])
def test_un_valor_vacio_o_unico_no_distingue_nada(valor):
    assert not v.es_valor_util(valor)


@pytest.mark.parametrize("valor", ["M", "2", "38-43", "128 GB", "Negro", "UNICO ELASTIZADO"])
def test_un_valor_real_si_distingue(valor):
    assert v.es_valor_util(valor)


def test_los_datos_tecnicos_nunca_son_una_variante():
    for id_atributo in ("GTIN", "SELLER_SKU", "PACKAGE_HEIGHT", "SELLER_PACKAGE_WEIGHT", "FILTRABLE_SIZE", "SIZE_GRID_ID", "SIZE_GRID_ROW_ID", "IS_OVERSIZE", "WITH_VIRTUAL_TRY_ON", "MAIN_COLOR", "ITEM_CONDITION"):
        assert v.es_tecnico(id_atributo), id_atributo
    for id_atributo in ("COLOR", "SIZE", "INTERNAL_MEMORY", "UNIT_VOLUME", "CAPACITY", "VOLTAGE", "BRAND"):
        assert not v.es_tecnico(id_atributo), id_atributo


def test_los_atributos_visibles_sacan_lo_tecnico_lo_oculto_y_lo_vacio():
    visibles = v.atributos_visibles(_iphone("Rosa", "128 GB") + [_a("FABRIC_DESIGN", "Único")], OCULTOS_CELULARES)
    assert sorted(visibles) == ["BRAND", "COLOR", "INTERNAL_MEMORY", "MODEL", "RAM"]
    assert v.mapa_clave(_iphone("Rosa", "128 GB"), OCULTOS_CELULARES) == {"BRAND": "Apple", "MODEL": "iPhone 15", "COLOR": "Rosa", "INTERNAL_MEMORY": "128 GB", "RAM": "6 GB"}


# ── Lo que cambia dentro de una familia ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_lo_que_cambia_entre_las_publicaciones_de_una_familia_es_lo_que_las_distingue():
    familia = [v.mapa_clave(_iphone(c, m, gtin=str(i)), OCULTOS_CELULARES) for i, (c, m) in enumerate((("Rosa", "128 GB"), ("Rosa", "256 GB"), ("Azul", "128 GB")))]
    assert v.atributos_que_cambian(familia) == {"COLOR", "INTERNAL_MEMORY"}              # la RAM, la marca y el modelo son iguales en todas; el GTIN es técnico
    assert v.atributos_que_cambian([familia[0]]) == set() and v.atributos_que_cambian([]) == set()


def test_la_marca_y_el_modelo_no_son_una_variante_aunque_cambien():
    assert v.atributos_que_cambian([{"BRAND": "A", "MODEL": "1", "COLOR": "Rojo"}, {"BRAND": "B", "MODEL": "2", "COLOR": "Rojo"}]) == set()


# ── El caso que rompía el regex: iPhone 14 y iPhone 15 ───────────────────────────────────────────────────────────────────────────────────
def test_la_variante_de_un_celular_sale_de_la_memoria_y_el_color_y_no_del_titulo():
    items = [(c, m) for c, m in (("Rosa", "128 GB"), ("Rosa", "256 GB"), ("Azul", "128 GB"))]
    familia = [v.mapa_clave(_iphone(c, m), OCULTOS_CELULARES) for c, m in items]
    distintivos = v.atributos_distintivos(familia, ["COLOR"])
    assert distintivos == ["INTERNAL_MEMORY", "COLOR"]
    etiquetas = []
    for c, m in items:
        atributos = v.atributos_de_variante(_iphone(c, m), None, ["COLOR"], distintivos, OCULTOS_CELULARES)
        etiquetas.append(v.etiqueta_de(atributos))
    assert etiquetas == ["128 GB / Rosa", "256 GB / Rosa", "128 GB / Azul"]               # lo que mide primero, el color al final
    assert v.talle_y_color(_iphone("Rosa", "128 GB")) == ("Único", "Rosa")             # un celular no tiene talle: ya no se inventa uno del título («Apple iPhone 15» → «15»)


def test_con_un_solo_miembro_en_la_familia_vale_lo_que_la_categoria_marca_como_variacion():
    atributos = v.atributos_de_variante(_iphone("Rosa", "128 GB"), None, ["COLOR"], [], OCULTOS_CELULARES)
    assert v.etiqueta_de(atributos) == "Rosa"                                              # no puede saber que la memoria distingue: no hay con qué comparar


def test_una_pintura_se_distingue_por_los_litros_y_el_color():
    def pintura(litros, color):
        return [_a("BRAND", "Obra Color"), _a("COLOR", color), _a("UNIT_VOLUME", litros, "Volumen de la unidad"), _a("PAINT_TYPE", "Látex")]
    familia = [v.mapa_clave(pintura(l, "Blanco")) for l in ("4 L", "20 L")]
    assert v.atributos_que_cambian(familia) == {"UNIT_VOLUME"}
    distintivos = v.atributos_distintivos(familia, ["COLOR"])
    assert distintivos == ["UNIT_VOLUME"]
    assert v.etiqueta_de(v.atributos_de_variante(pintura("20 L", "Blanco"), None, ["COLOR"], distintivos)) == "20 L"


# ── Ropa: talle «Único», color, y las columnas viejas ────────────────────────────────────────────────────────────────────────────────────
def _buzo(talle, color, diseno="Liso"):
    return [_a("BRAND", "Genérica"), _a("COLOR", color, "Color"), _a("SIZE", talle, "Talle"), _a("FABRIC_DESIGN", diseno, "Diseño de la tela"), _a("FILTRABLE_SIZE", "XL,2XL,3XL"), _a("GENDER", "Mujer")]


def test_un_talle_unico_no_aparece_en_la_etiqueta_ni_en_las_columnas_viejas():
    atributos = v.atributos_de_variante(_buzo("Único", "Natural"), None, ["COLOR", "SIZE", "FABRIC_DESIGN"], [])
    assert [a["id"] for a in atributos] == ["FABRIC_DESIGN", "COLOR"] and v.etiqueta_de(atributos) == "Liso / Natural"
    assert v.talle_y_color(_buzo("Único", "Natural")) == ("Único", "Natural")


DIMENSIONES_ROPA = ["COLOR", "SIZE", "FABRIC_DESIGN"]


def test_en_una_familia_de_ropa_solo_aparece_lo_que_cambia():
    hermanas = [_buzo("2", "Chocolate"), _buzo("3", "Chocolate"), _buzo("2", "Beige")]
    mapas = [v.mapa_clave(h) for h in hermanas]
    assert v.atributos_que_cambian(mapas) == {"SIZE", "COLOR"}                           # el diseño de la tela es igual en todas: no ensucia la etiqueta
    distintivos = v.atributos_distintivos(mapas, DIMENSIONES_ROPA)
    etiquetas = [v.etiqueta_de(v.atributos_de_variante(h, None, DIMENSIONES_ROPA, distintivos)) for h in hermanas]
    assert etiquetas == ["2 / Chocolate", "3 / Chocolate", "2 / Beige"]
    assert v.talle_y_color(hermanas[0]) == ("2", "Chocolate")


def test_un_atributo_que_cambia_pero_no_hace_falta_no_ensucia_la_etiqueta():
    """Caso real de la cuenta de prueba: la composición de la tela cambia entre algunas hermanas, pero talle y color ya las distinguen."""
    def buzo(talle, color, composicion):
        return _buzo(talle, color) + [_a("COMPOSITION", composicion, "Composición")]
    hermanas = [buzo("4", "Negro", "Algodón"), buzo("5", "Negro", "Algodón,Spandex"), buzo("4", "Gris", "Algodón")]
    mapas = [v.mapa_clave(h) for h in hermanas]
    assert "COMPOSITION" in v.atributos_que_cambian(mapas)
    assert v.atributos_distintivos(mapas, DIMENSIONES_ROPA) == ["SIZE", "COLOR"]
    # pero si dos hermanas solo se diferencian por la composición, entonces sí hace falta
    iguales = [buzo("4", "Negro", "Algodón"), buzo("4", "Negro", "Poliéster")]
    mapas = [v.mapa_clave(h) for h in iguales]
    assert v.atributos_distintivos(mapas, DIMENSIONES_ROPA) == ["COMPOSITION"]
    assert [v.etiqueta_de(v.atributos_de_variante(h, None, DIMENSIONES_ROPA, ["COMPOSITION"])) for h in iguales] == ["Algodón", "Poliéster"]


def test_dos_publicaciones_identicas_no_arrastran_atributos_de_mas():
    mapas = [{"COLOR": "Negro", "SIZE": "M", "COMPOSITION": "Algodón"}, {"COLOR": "Negro", "SIZE": "M", "COMPOSITION": "Algodón"}]
    assert v.atributos_distintivos(mapas, DIMENSIONES_ROPA) == [] and v.atributos_distintivos([], DIMENSIONES_ROPA) == []


def test_el_talle_viejo_sale_en_mayusculas_y_solo_del_atributo():
    assert v.talle_y_color([_a("SIZE", "xl"), _a("COLOR", "Verde")]) == ("XL", "Verde")
    assert v.talle_y_color([_a("SIZE", "38-43")]) == ("38-43", "Único")
    assert v.talle_y_color([]) == ("Único", "Único") and v.talle_y_color(None) == ("Único", "Único")


# ── Publicaciones con variaciones clásicas ───────────────────────────────────────────────────────────────────────────────────────────────
def test_en_una_variacion_clasica_la_variante_son_sus_attribute_combinations():
    combinaciones = [{"id": "COLOR", "name": "Color", "value_id": "1", "value_name": "Negro"}, {"id": "SIZE", "name": "Talle", "value_id": "2", "value_name": "M"}]
    atributos = v.atributos_de_variante(_buzo("Único", "Natural"), combinaciones, ["COLOR", "SIZE"], [])
    assert v.etiqueta_de(atributos) == "M / Negro"                                       # lo de la variación manda sobre los atributos de la publicación
    assert v.talle_y_color(_buzo("Único", "Natural"), combinaciones) == ("M", "Negro")


def test_las_columnas_viejas_leen_la_variacion_por_nombre_cuando_no_trae_id():
    combinaciones = [{"name": "Color", "value_name": "Rojo"}, {"name": "Talle", "value_name": "s"}]
    assert v.talle_y_color([], combinaciones) == ("S", "Rojo")


def test_una_publicacion_sin_nada_que_la_distinga_es_unica():
    assert v.etiqueta_de([]) == "Única" and v.etiqueta_de(None) == "Única"
    assert v.etiqueta_de(v.atributos_de_variante([_a("BRAND", "X")], None, ["COLOR"], [])) == "Única"


def test_la_etiqueta_no_repite_un_valor_igual_en_dos_atributos():
    assert v.etiqueta_de([{"id": "A", "value_name": "Negro"}, {"id": "B", "value_name": "negro"}, {"id": "C", "value_name": "M"}]) == "Negro / M"


def test_un_atributo_numerico_conserva_su_estructura():
    atributo = v.atributos_visibles([_a("INTERNAL_MEMORY", "128 GB", value_struct={"number": 128, "unit": "GB"})])["INTERNAL_MEMORY"]
    assert atributo["value_struct"] == {"number": 128, "unit": "GB"} and atributo["value_name"] == "128 GB"

import pytest
from utils import extraer_talle, limpiar_titulo_modelo


@pytest.mark.parametrize("titulo, esperado", [
    ("Campera Jean Negro XL", "XL"),
    ("Campera Jean Negro Talle L", "L"),
    ("Remera Algodon Talle 3", "3"),
    ("Chaleco Inflable Lisa 7", "7"),              # número suelto AL FINAL: es talle
    ("Combo 2 Termos Acero Inoxidable 1l", "Único"),  # número en el medio: no es talle
    ("Perfume 50 ml", "Único"),
    ("Pack 12 Medias", "Único"),
    ("Termo Acero 1 Litro", "Único"),
    ("", "Único"),
    (None, "Único"),
])
def test_extraer_talle_del_titulo(titulo, esperado):
    assert extraer_talle(titulo) == esperado


def test_el_talle_real_de_mercado_libre_gana_sobre_el_titulo():
    assert extraer_talle("Medias Pack Docena", "38-43") == "38-43"
    assert extraer_talle("Campera Negro XL", "m") == "M"
    assert extraer_talle("Campera Negro XL", "Único") == "XL"      # "Único" no es un dato: se mira el título


def test_clave_de_modelo_agrupa_los_talles():
    base = "Campera De Jean Hombre Negro"
    assert limpiar_titulo_modelo(base + " XL") == limpiar_titulo_modelo(base + " L") == base
    assert limpiar_titulo_modelo(base + " Talle 3") == base
    assert limpiar_titulo_modelo(None) == ""


def test_dos_productos_distintos_no_se_agrupan():
    assert limpiar_titulo_modelo("Pack 12 Medias") != limpiar_titulo_modelo("Pack 6 Medias")


def test_html_seguro_deja_el_formato_y_descarta_lo_peligroso():
    from utils import html_seguro
    assert html_seguro("<b>3 reclamos</b> abiertos") == "<b>3 reclamos</b> abiertos"
    assert html_seguro('<b>Ok</b><script>alert(1)</script>') == "<b>Ok</b>"
    assert html_seguro('<img src=x onerror=alert(1)>hola') == "hola"
    assert "onclick" not in html_seguro('<span class="a" onclick="x()">t</span>') and 'class="a"' in html_seguro('<span class="a" onclick="x()">t</span>')
    assert "javascript" not in html_seguro('<a href="javascript:alert(1)">x</a>')
    assert html_seguro('<a href="/stock">ir</a>') == '<a href="/stock">ir</a>'
    assert html_seguro("5 < 6 & 7 > 2") == "5 &lt; 6 &amp; 7 &gt; 2"
    assert html_seguro(None) == ""


def test_el_momento_en_hora_argentina_unifica_filas_viejas_y_nuevas():
    from utils import sql_momento_argentina
    sql = sql_momento_argentina()
    assert "CASE WHEN hora_normalizada THEN INTERVAL '0 hour' ELSE INTERVAL '1 hour' END" in sql
    assert "COALESCE(hora_venta, TIME '00:00')" in sql
    assert "v.hora_normalizada" in sql_momento_argentina("v") and "TIME '12:00'" in sql_momento_argentina(por_defecto="12:00")
    with pytest.raises(ValueError):
        sql_momento_argentina(por_defecto="12:00'; DROP TABLE ventas; --")
    with pytest.raises(ValueError):
        sql_momento_argentina(prefijo="v; --")


def test_vocabulario_segun_la_cuenta():
    from utils import vocabulario
    assert vocabulario(True) == {"v1": "talle", "vN": "talles", "V1": "Talle", "VN": "Talles"}
    v = vocabulario(False)
    assert (v["v1"], v["vN"], v["V1"], v["VN"]) == ("variante", "variantes", "Variante", "Variantes")

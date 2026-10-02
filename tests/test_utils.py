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


@pytest.mark.parametrize("valor, esperado", [
    (1234567.89, "1.234.568"),      # sin centavos: en análisis no cambian ninguna decisión
    (-0.4, "0"),                     # nunca "-0"
    (-1500.5, "-1.500"),
    (None, "0"),
    ("no es número", "0"),
])
def test_formatear_moneda_en_pesos_enteros(valor, esperado):
    import utils
    assert utils.formatear_moneda(valor) == esperado


def test_plural_nunca_deja_la_s_entre_parentesis():
    import utils
    assert utils.plural(1, "venta") == "1 venta"
    assert utils.plural(3, "venta") == "3 ventas"
    assert utils.plural(2, "devolución", "devoluciones") == "2 devoluciones"
    assert utils.plural(1500, "unidad", "unidades") == "1.500 unidades"


@pytest.mark.parametrize("viejo, nuevo", [
    ("1 reclamo(s) sin resolver", "1 reclamo sin resolver"),
    ("3 devolución(es) o reclamo(s) por gestionar", "3 devoluciones o reclamos por gestionar"),
    ("2 promoción(es) activa(s) sin impacto real", "2 promociones activas sin impacto real"),
    ("Sin paréntesis", "Sin paréntesis"),
])
def test_corregir_plurales_de_textos_guardados(viejo, nuevo):
    import utils
    assert utils.corregir_plurales(viejo) == nuevo


def test_fechas_para_mostrar(monkeypatch):
    import datetime as dt
    import utils
    monkeypatch.setattr(utils, "hoy_argentina", lambda: dt.date(2026, 10, 2))
    assert utils.fecha_corta("2026-09-02") == "2 sep"
    assert utils.fecha_corta(dt.date(2025, 12, 28)) == "28 dic 2025"       # de otro año: con el año
    assert utils.fecha_corta("hace 2 días") == "hace 2 días"                # un texto que no es fecha se muestra tal cual
    assert utils.fecha_corta(None) == "—"
    assert utils.rango_fechas("2026-09-02", "2026-10-02") == "2 sep – 2 oct"
    assert utils.rango_fechas("2026-10-05", "2026-10-12") == "5 – 12 oct"
    assert utils.rango_fechas("2025-12-28", "2026-01-03") == "28 dic 2025 – 3 ene"
    assert utils.cuando_corto(dt.datetime(2026, 10, 2, 14, 32)) == "Hoy 14:32"
    assert utils.cuando_corto(dt.datetime(2026, 10, 1, 21, 5)) == "Ayer 21:05"
    assert utils.cuando_corto(dt.datetime(2026, 9, 28, 9, 0)) == "28 sep 09:00"
    assert utils.cuando_corto(dt.datetime(2026, 9, 28, 0, 0), con_hora=False) == "28 sep"


def test_una_tendencia_solo_esta_cubierta_si_aparece_en_algun_titulo():
    """La pantalla mostraba como "ya cubierto" todo lo que no entraba en las 5 oportunidades (\"nike\" para quien vende camperas sin marca)."""
    import tendencias

    class Cursor:
        def execute(self, *a):
            pass

        def fetchall(self):
            return [("MLA1", "Campera De Jean Hombre Negra"), ("MLA2", "Medias Algodon Pack")]

    tendencias_ = [{"keyword": k} for k in ("campera de jean", "medias", "nike", "lacoste", "gorras", "short", "bolso", "puma")]
    oportunidades = tendencias.cruzar_tendencias_con_catalogo(tendencias_, Cursor())
    cubiertas = {t["keyword"] for t in tendencias_ if t.get("cubierta")}
    assert cubiertas == {"campera de jean", "medias"}
    assert len(oportunidades) == 5 and not {o["termino"] for o in oportunidades} & cubiertas

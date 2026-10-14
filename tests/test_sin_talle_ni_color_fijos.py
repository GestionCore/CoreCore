"""
Ninguna pantalla, archivo ni pregunta a la IA da por hecho que se vende ropa: no hay columnas fijas «Talle» o «Color». Lo que distingue a una variante (M / Negro, 128 GB / Azul, 4 L)
se muestra con su nombre real —`utils.rotulo_variante`— y, cuando hace falta una palabra, la que da `vocab` según la cuenta (ver utils.vocabulario).
"""
import glob
import inspect
import os
import re

import pytest

import utils

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_APP = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: importar app abre el pool")


def test_el_rotulo_de_una_variante_es_su_etiqueta_y_si_no_el_valor_de_size():
    assert utils.rotulo_variante("128 GB / Azul", "Único") == "128 GB / Azul"
    assert utils.rotulo_variante("M / Negro", "M") == "M / Negro"
    assert utils.rotulo_variante(None, "m") == "M" and utils.rotulo_variante("", " xl ") == "XL"          # sin etiqueta todavía: el SIZE de Mercado Libre
    for nada in ((None, None), ("Única", "Único"), ("  ", "UNICO"), ("unica", None)):
        assert utils.rotulo_variante(*nada) == "Única"                                                  # nada la distingue


def _texto_visible(fuente):
    """La plantilla sin Jinja ni comentarios: lo que queda es lo que se escribió a mano y se ve."""
    sin = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}|<!--.*?-->", " ", fuente, flags=re.S)
    return re.sub(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", " ", sin, flags=re.S)                 # comentarios de CSS y JS


def test_ninguna_plantilla_escribe_talle_ni_color_a_mano():
    hallazgos = []
    for ruta in sorted(glob.glob(os.path.join(RAIZ, "templates", "**", "*.html"), recursive=True)):
        fuente = open(ruta, encoding="utf-8").read()
        rel = os.path.relpath(ruta, RAIZ)
        for n, linea in enumerate(fuente.splitlines(), 1):
            if re.search(r"\.talle\b|(?<!style)\.color\b|\bc-talle\b|-talle\b", linea):
                hallazgos.append(f"{rel}:{n} usa el campo «talle»/«color» en vez de `variante`")
        for m in re.finditer(r"\b[Tt]alles?\b|\bColor(?:es)?\b", _texto_visible(fuente)):
            hallazgos.append(f"{rel}: escribe «{m.group(0)}» a mano (usar `variante` o `vocab`)")
    assert not hallazgos, "\n".join(hallazgos)


def _fuente_python(archivo):
    return open(os.path.join(RAIZ, archivo), encoding="utf-8").read()


def test_los_prompts_de_ia_no_nombran_talles_ni_colores():
    prompts = []
    for ruta in glob.glob(os.path.join(RAIZ, "*.py")):
        for m in re.finditer(r"((?:prompt|PROMPT)\w*\s*=\s*\(?\s*(?:f?\"[^\n]*\"\s*)+)", open(ruta, encoding="utf-8").read()):
            prompts.append((os.path.basename(ruta), m.group(1)))
    assert prompts, "no se encontró ningún prompt: la prueba dejó de mirar"
    malos = [(a, t[:80]) for a, t in prompts if re.search(r"\b[Tt]alles?\b|\b[Cc]olor(?:es)?\b|ropa|indumentaria", t)]
    assert not malos, malos


@CON_APP
def test_el_excel_del_balance_trae_una_columna_variante_y_ninguna_de_talle_o_color():
    from io import BytesIO

    from openpyxl import load_workbook

    import metricas
    raw = {"facturado": 1, "comision": 0, "envios": 0, "costo_ads": 0, "costo_fabricacion": 0, "cargos_fuera_de_ventas": 0, "ganancia_neta": 1}
    datos = {"resumen": {"raw": raw}, "posventa": {"devoluciones": 0, "cancelaciones": 0, "reclamos": 0, "dinero_retenido_monto": 0}, "consolidados": [],
             "ventas": [{"fecha": "2026-10-01", "id_orden": "o1", "titulo": "Termo", "variante": "1 L / Negro", "cantidad": 1,
                         "raw": {"precio_venta": 1, "cargo_venta": 0, "costo_envio": 0, "costo_ads": 0, "costo_fabricacion": 0, "ganancia_neta": 1}}]}
    libro = load_workbook(BytesIO(metricas.generar_excel_balance(datos, "2026-10-01", "2026-10-31").getvalue()))
    encabezado = [c.value for c in libro["Detalle de ventas"][1]]
    assert "Variante" in encabezado and not {"Talle", "Color"} & set(encabezado)
    assert libro["Detalle de ventas"][2][encabezado.index("Variante")].value == "1 L / Negro"


@CON_APP
def test_la_planilla_de_stock_trae_una_columna_variante_y_ninguna_de_talle_o_color(monkeypatch):
    import csv
    from io import StringIO

    import app as aplicacion
    import db

    class _Cursor:
        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return [("MLA1", "Termo", "Único", "1 L / Negro", 15000, "active", 3, 0), ("MLA2", "Buzo", "M", None, 20000, "active", 1, 2), ("MLA3", "Gorra", None, None, 5000, "active", 0, 0)]

    class _Conexion:
        def cursor(self):
            return _Cursor()

    class _Prestada:
        def __enter__(self):
            return _Conexion()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _Prestada())
    funcion = inspect.unwrap(aplicacion.exportar_planilla_stock)
    with aplicacion.app.test_request_context("/exportar_planilla_stock"):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = 1, 1
        respuesta = funcion()
        respuesta.direct_passthrough = False                                                              # para poder leer el cuerpo del archivo
        filas = list(csv.reader(StringIO(respuesta.get_data().decode("utf-8-sig")), delimiter=";"))
    assert filas[0] == ["ID MeLi", "Título", "Variante", "Precio", "Estado", "Stock Propio", "Stock FULL"]
    assert [f[2] for f in filas[1:]] == ["1 L / Negro", "M", "Única"]


def test_ninguna_columna_de_los_archivos_exportados_se_llama_talle_o_color():
    for archivo in ("app.py", "metricas.py", "reporte_fiscal.py", "costos_importar.py"):
        for m in re.finditer(r"(?:writerow|_armar_header|append)\(\s*\[([^\]\n]*)\]", _fuente_python(archivo)):
            assert not re.search(r"\"(?:Talle|Color)\"", m.group(1)), f"{archivo}: una columna fija «Talle»/«Color» en {m.group(0)[:80]}"

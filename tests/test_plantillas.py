import glob
import os
import re

import jinja2
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTILLAS = sorted(os.path.basename(p) for p in glob.glob(os.path.join(RAIZ, "templates", "*.html")))
# Los filtros que registra app.py (sin importarlo: eso abriría la base). Una plantilla que use un filtro no registrado no compila.
FILTROS_APP = re.findall(r'add_template_filter\([\w.]+,\s*"(\w+)"\)', open(os.path.join(RAIZ, "app.py"), encoding="utf-8").read())


@pytest.mark.parametrize("nombre", PLANTILLAS)
def test_la_plantilla_compila(nombre):
    """Una plantilla con un error de sintaxis Jinja rompe la pantalla recién cuando alguien la abre: acá se detecta antes."""
    entorno = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(RAIZ, "templates")))
    for filtro in FILTROS_APP:
        entorno.filters[filtro] = lambda x, *a, **k: x
    entorno.get_template(nombre)


def test_se_leyeron_los_filtros_de_la_app():
    assert {"plata", "pct", "numero", "fecha", "plural"} <= set(FILTROS_APP)


def test_costos_ofrece_el_excel_antes_que_flex_y_sin_depender_de_flex():
    """El Excel es la vía rápida para empezar: va primero y se ve aunque la cuenta no tenga Flex (el condicional de Flex no puede envolverlo)."""
    t = open(os.path.join(RAIZ, "templates", "costos.html"), encoding="utf-8").read()
    condicional = t.index("{% if capacidades.get('flex') is not false %}")
    assert t.index('id="importar-costos"') < condicional < t.index('id="entrega-flex"')


def test_ninguna_plantilla_concatena_html_con_texto_ya_escapado():
    """Con autoescape, "<b>" ~ (texto|e) devuelve Markup y escapa TAMBIÉN el "<b>": la persona ve las etiquetas escritas (pasó en Logros y en
    Ventas fuera de MeLi). El texto externo va sin |e (las macros lo pasan por ux_seguro) o en el detalle, que se escapa solo."""
    patron = re.compile(r"\|e\b\s*\)?\s*~|~\s*\(?\s*[\w.\[\]]+\s*\|e\b")
    culpables = []
    for nombre in PLANTILLAS:
        for n, linea in enumerate(open(os.path.join(RAIZ, "templates", nombre), encoding="utf-8"), 1):
            if patron.search(linea) and not linea.strip().startswith("//"):
                culpables.append(f"{nombre}:{n}")
    assert not culpables, culpables


def test_todo_boton_declara_su_tipo():
    """Un <button> sin type dentro de un formulario envía el formulario: hay que decir type="button" (o "submit") siempre."""
    sin_tipo = []
    for nombre in PLANTILLAS:
        for n, linea in enumerate(open(os.path.join(RAIZ, "templates", nombre), encoding="utf-8"), 1):
            for boton in re.findall(r"<button\b[^>]*>", linea):
                if "type=" not in boton:
                    sin_tipo.append(f"{nombre}:{n}")
    assert not sin_tipo, sin_tipo

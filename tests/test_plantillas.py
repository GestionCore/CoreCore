import glob
import os
import jinja2
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTILLAS = sorted(os.path.basename(p) for p in glob.glob(os.path.join(RAIZ, "templates", "*.html")))


@pytest.mark.parametrize("nombre", PLANTILLAS)
def test_la_plantilla_compila(nombre):
    """Una plantilla con un error de sintaxis Jinja rompe la pantalla recién cuando alguien la abre: acá se detecta antes."""
    entorno = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(RAIZ, "templates")))
    for filtro in ("plata", "pct", "numero", "ux_seguro"):
        entorno.filters[filtro] = lambda x, *a, **k: x
    entorno.get_template(nombre)


def test_costos_ofrece_el_excel_antes_que_flex_y_sin_depender_de_flex():
    """El Excel es la vía rápida para empezar: va primero y se ve aunque la cuenta no tenga Flex (el condicional de Flex no puede envolverlo)."""
    t = open(os.path.join(RAIZ, "templates", "costos.html"), encoding="utf-8").read()
    condicional = t.index("{% if capacidades.get('flex') is not false %}")
    assert t.index('id="importar-costos"') < condicional < t.index('id="entrega-flex"')

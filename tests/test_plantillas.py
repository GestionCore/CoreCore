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

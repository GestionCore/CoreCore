"""Reglas de CSS que, si se rompen, fallan en silencio (el botón "ver más" no esconde nada, un menú queda siempre abierto…)."""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css(nombre):
    return open(os.path.join(RAIZ, "static", "css", nombre), encoding="utf-8").read()


def test_oculto_mostrar_mas_gana_siempre():
    """Es una utilidad: tiene que ocultar aunque el elemento tenga su propio display (ux-rank-fila es flex y se carga después)."""
    regla = re.search(r"\.oculto-mostrar-mas\s*\{([^}]*)\}", _css("style.css"))
    assert regla and "display: none !important" in regla.group(1)


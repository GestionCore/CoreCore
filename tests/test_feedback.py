import os

import pytest

import feedback


@pytest.mark.parametrize("tipo, mensaje, ok", [
    ("problema", "No me carga la pantalla de costos", True),
    ("idea", "  Estaría bueno ver el mes anterior  ", True),
    ("pregunta", "¿Cómo cargo el costo de varios productos?", True),
    ("otro", "algo válido pero tipo inválido", False),
    (None, "algo válido pero sin tipo", False),
    ("idea", "hola", False),                     # muy corto
    ("idea", "", False),
    ("idea", None, False),
    ("idea", "x" * 2001, False),                 # muy largo
])
def test_validar(tipo, mensaje, ok):
    t, m, error = feedback.validar(tipo, mensaje)
    assert (error is None) is ok
    if ok:
        assert t == tipo and m == mensaje.strip()


def test_los_saltos_de_linea_se_conservan_pero_no_se_acumulan():
    _, m, _ = feedback.validar("problema", "Primera línea\n\n\n\n\nSegunda línea")
    assert m == "Primera línea\n\nSegunda línea"


def test_todos_los_tipos_de_la_interfaz_existen_en_el_servidor():
    """Los botones de la ventana (base.html) mandan estos valores: si cambian en un lado y no en el otro, el comentario se rechaza."""
    import re
    base = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "base.html"), encoding="utf-8").read()
    en_pantalla = set(re.findall(r'class="fb-tipo[^"]*" data-tipo="(\w+)"', base))
    assert en_pantalla == set(feedback.TIPOS)

"""
Los campos (input, select, textarea) se tienen que ver: WCAG 1.4.11 pide 3:1 entre el borde de un control y lo que tiene alrededor. Antes el borde de los campos era el de las tarjetas (casi invisible a propósito:
1,19:1 en oscuro), y en las pantallas con muchos campos (Costos tiene 218) no se distinguía dónde se escribe (auditoría de diseño, D13, 2026-10-21). Las tarjetas conservan su borde casi invisible.
Los contrastes se calculan con la fórmula de WCAG y los colores escritos en el CSS.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    return open(os.path.join(RAIZ, "static", "css", "style.css"), encoding="utf-8").read()


def _luminancia(color):
    color = color.lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lineal = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b)


def contraste(a, b):
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _variable(selector, nombre):
    sin_comentarios = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", sin_comentarios):
        if m.group(1).strip() == selector and "--" in m.group(2):
            hallado = re.search(rf"--{nombre}:\s*(#[0-9a-fA-F]{{6}})", m.group(2))
            if hallado:
                return hallado.group(1)
    raise AssertionError(f"no está --{nombre} en {selector}")


def test_el_borde_de_los_campos_llega_a_3_a_1_en_los_dos_temas():
    for selector, fondos in ((":root", ("glass-bg", "bg-base", "bg-surface")), (':root[data-theme="light"]', ("bg-base", "bg-surface"))):
        borde = _variable(selector, "campo-borde")
        for nombre in fondos:
            fondo = _variable(selector, nombre)
            assert contraste(borde, fondo) >= 3.0, (selector, borde, nombre, fondo, round(contraste(borde, fondo), 2))


def test_la_regla_de_los_campos_usa_ese_borde_y_no_el_de_las_tarjetas():
    css = _css()
    regla = re.search(r'input\[type="text"\], input\[type="number"\], input\[type="date"\], select, textarea \{([^}]*)\}', css)
    assert regla, "no se encontró la regla base de los campos"
    assert "border: 1px solid var(--campo-borde)" in regla.group(1)
    assert "glass-border" not in regla.group(1)

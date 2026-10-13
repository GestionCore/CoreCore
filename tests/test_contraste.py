"""
Contraste de color (WCAG AA) del tema claro y del oscuro, medido sobre los tokens REALES de static/css/style.css.

Los textos de color de la app (verde de ganancia, rojo de pérdida, naranja de alerta, celeste de información, violeta de acción) se dibujan sobre la tarjeta y, en banners, píldoras,
KPI y sellos, sobre un fondo teñido con ese mismo color (`color-mix(in srgb, var(--ux-c) N%, ...)` con N entre 4 y 24). Antes, en modo claro, el verde daba 3,7:1 sobre la tarjeta
y 3,0:1 sobre su fondo teñido: no se leía. Esta prueba falla si algún par baja de 4,5:1 (WCAG AA para texto normal).
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = open(os.path.join(RAIZ, "static", "css", "style.css"), encoding="utf-8").read()
MINIMO = 4.5
TINTES = (0.04, 0.10, 0.14, 0.18, 0.24)             # los porcentajes que usan ux.css y style.css para teñir un fondo con el color del componente
SEMANTICOS = ("success", "danger", "semantic-warning", "semantic-info", "ux-accion", "accent-gold", "semantic-achieve")


def _bloque(inicio):
    desde = CSS.index(inicio)
    return CSS[desde:CSS.index("\n}", desde)]


def _tokens(bloque):
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"--([\w-]+):\s*([^;]+?);", bloque)}


OSCURO = _tokens(_bloque(":root {"))
CLARO = {**OSCURO, **_tokens(_bloque(':root[data-theme="light"] {'))}


def _rgb(texto, tokens, fondo=None):
    """Valor CSS (#hex, rgba(), var(--x)) -> (r, g, b); un rgba con transparencia se compone sobre `fondo`."""
    texto = texto.strip()
    m = re.fullmatch(r"var\(--([\w-]+)(?:,\s*[^)]*)?\)", texto)
    if m:
        return _rgb(tokens[m.group(1)], tokens, fondo)
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", texto)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\s*\)", texto)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        alfa = float(m.group(4)) if m.group(4) is not None else 1.0
        if alfa < 1 and fondo is not None:
            return tuple(fondo[i] * (1 - alfa) + (r, g, b)[i] * alfa for i in range(3))
        return (r, g, b)
    raise ValueError(f"no se entiende el valor {texto!r}")


def _luminancia(rgb):
    def lineal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lineal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mezcla(fondo, color, p):
    return tuple(fondo[i] * (1 - p) + color[i] * p for i in range(3))


def _tarjeta(tokens):
    base = _rgb(tokens["bg-base"], tokens)
    return _rgb(tokens["glass-bg"], tokens, fondo=base)


# ── Tema claro ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token", SEMANTICOS)
def test_en_claro_el_color_semantico_se_lee_como_texto_sobre_la_tarjeta_y_sobre_su_propio_fondo_teñido(token):
    color, tarjeta = _rgb(CLARO[token], CLARO), _tarjeta(CLARO)
    peores = {"tarjeta": contraste(color, tarjeta), **{f"{int(p * 100)} %": contraste(color, _mezcla(tarjeta, color, p)) for p in TINTES}}
    assert min(peores.values()) >= MINIMO, f"--{token} {CLARO[token]}: {({k: round(v, 2) for k, v in peores.items()})}"


@pytest.mark.parametrize("token", ("text-primary", "text-secondary", "text-faint", "accent-texto"))
def test_en_claro_los_textos_neutros_se_leen_sobre_la_tarjeta_y_sobre_un_fondo_teñido(token):
    color, tarjeta = _rgb(CLARO[token], CLARO), _tarjeta(CLARO)
    pasos = [tarjeta] + [_mezcla(tarjeta, _rgb(CLARO["accent-primary"], CLARO), p) for p in (0.10, 0.18)]
    assert min(contraste(color, fondo) for fondo in pasos) >= MINIMO, token


@pytest.mark.parametrize("token", SEMANTICOS + ("text-secondary",))
def test_en_claro_el_texto_sobre_una_pastilla_de_color_solido_es_legible(token):
    """Las pastillas (`ux-pill`), el ícono de los banners y el aviso (toast) pintan el texto con --texto-sobre-color sobre el color sólido."""
    assert contraste(_rgb(CLARO["texto-sobre-color"], CLARO), _rgb(CLARO[token], CLARO)) >= MINIMO, token


@pytest.mark.parametrize("insignia, texto", [("success-bg", "success"), ("danger-bg", "danger"), ("semantic-warning-bg", "semantic-warning"), ("semantic-info-bg", "semantic-info"), ("semantic-achieve-bg", "semantic-achieve")])
def test_en_claro_las_insignias_de_color_se_leen(insignia, texto):
    tarjeta = _tarjeta(CLARO)
    fondo = _rgb(CLARO[insignia], CLARO, fondo=tarjeta)
    assert contraste(_rgb(CLARO[texto], CLARO), fondo) >= MINIMO


def test_en_claro_el_color_de_accion_de_los_botones_sigue_siendo_el_violeta_de_identidad():
    """El texto de acción se oscurece (--ux-accion), pero el violeta de los botones y de la identidad no cambia: texto blanco sobre él llega a 4,5:1."""
    assert CLARO["accent-primary"] == "#8b3ffc"
    assert contraste((255, 255, 255), _rgb(CLARO["accent-primary"], CLARO)) >= MINIMO


# ── Tema oscuro: lo que no se debe romper ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token", ("text-primary", "text-secondary", "text-faint", "accent-texto", "success", "semantic-warning", "semantic-info", "accent-gold"))
def test_en_oscuro_estos_textos_se_leen_sobre_la_tarjeta(token):
    assert contraste(_rgb(OSCURO[token], OSCURO), _tarjeta(OSCURO)) >= MINIMO, token


@pytest.mark.parametrize("token", ("success", "danger", "semantic-warning", "semantic-info", "accent-gold", "text-secondary"))
def test_en_oscuro_el_texto_sobre_una_pastilla_de_color_solido_es_legible(token):
    assert contraste(_rgb(OSCURO["texto-sobre-color"], OSCURO), _rgb(OSCURO[token], OSCURO)) >= MINIMO, token


def test_el_css_usa_el_token_de_texto_sobre_color_y_no_un_negro_fijo():
    ux = open(os.path.join(RAIZ, "static", "css", "ux.css"), encoding="utf-8").read()
    assert "color: #0a0a0c; box-shadow" not in ux and "background: var(--ux-c); color: #0a0a0c" not in ux
    assert "var(--texto-sobre-color" in ux and "color: #06201a" not in CSS

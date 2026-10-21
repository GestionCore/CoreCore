"""
Violeta de los fondos con texto blanco (`--accent-solid`) y dorado de la marca en el tema claro. Aprobado por el dueño el 2026-10-21 a partir de la auditoría de diseño (D15 y D46).

· El violeta de identidad (#8b5cf6) con texto blanco daba 4,23:1 (AA pide 4,5:1): filtros activos («Todos», «Activas», «Clásica»), contadores, el chip del período elegido, la inicial de la cuenta…
  `--accent-solid` (#8652f3 en oscuro; el propio violeta en claro, que ya da 4,98:1) lo reemplaza SOLO donde hay texto blanco encima: bordes, íconos y textos siguen con el violeta de siempre.
· En el tema claro el dorado de texto es un marrón (#92400e, para llegar a 4,5:1 sobre sus fondos teñidos) y la marca salía marrón: ahora lleva su propio dorado oscuro.
Los contrastes se calculan acá con la fórmula de WCAG, con los colores que están escritos en el CSS.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


def _luminancia(color):
    color = color.lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lineal = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b)


def contraste(a, b):
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _bloque(css, selector):
    """El cuerpo de la primera regla cuyo selector EMPIEZA con `selector` (los dos temas definen sus variables en `:root` y `:root[data-theme="light"]`)."""
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", sin_comentarios):
        if m.group(1).strip() == selector and "--" in m.group(2):                     # la regla con las variables (el tema claro tiene otra, solo con `color-scheme`)
            return m.group(2)
    raise AssertionError(f"no está la regla {selector}")


def _variable(css, selector, nombre):
    return re.search(rf"--{nombre}:\s*(#[0-9a-fA-F]{{6}})", _bloque(css, selector)).group(1)


def test_el_violeta_solido_llega_a_4_5_con_texto_blanco_en_los_dos_temas():
    css = _leer("static", "css", "style.css")
    solido_oscuro = _variable(css, ":root", "accent-solid")
    assert contraste("#ffffff", solido_oscuro) >= 4.5, solido_oscuro
    assert contraste("#ffffff", "#8b5cf6") < 4.5                                   # el de antes: por eso se cambia
    # en el tema claro el sólido ES el violeta primario (que ya llegaba), y el extremo oscuro del degradé también
    bloque_claro = _bloque(css, ':root[data-theme="light"]')
    assert re.search(r"--accent-solid:\s*var\(--accent-primary\)", bloque_claro)
    assert contraste("#ffffff", _variable(css, ':root[data-theme="light"]', "accent-primary")) >= 4.5
    assert contraste("#ffffff", _variable(css, ':root[data-theme="light"]', "accent-primary-dim")) >= 4.5
    assert contraste("#ffffff", _variable(css, ":root", "accent-primary-dim")) >= 4.5      # extremo oscuro del degradé de los botones, en el tema oscuro


def test_el_violeta_solido_se_distingue_del_fondo_como_componente():
    """Un botón o chip violeta tiene que verse contra la tarjeta (3:1, WCAG 1.4.11)."""
    css = _leer("static", "css", "style.css")
    solido = _variable(css, ":root", "accent-solid")
    for fondo in ("#14141a", "#0a0a0c"):
        assert contraste(solido, fondo) >= 3.0, (solido, fondo)


def test_ningun_fondo_violeta_lleva_texto_blanco_con_el_violeta_de_identidad():
    """Toda regla con `color: #fff` y fondo violeta usa `--accent-solid` (no `--accent-primary`/`--accent-denim` a secas): un `--accent-primary` nuevo con texto blanco vuelve a dar 4,23:1."""
    sospechosas = []
    textos = {f"static/css/{n}": _leer("static", "css", n) for n in ("style.css", "ux.css", "shell.css", "movil.css")}
    for plantilla in sorted(os.listdir(os.path.join(RAIZ, "templates"))):
        if plantilla.endswith(".html"):
            textos[f"templates/{plantilla}"] = _leer("templates", plantilla)
    for origen, texto in textos.items():
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", texto):
            cuerpo = m.group(2)
            blanco = re.search(r"(?<![-\w])color:\s*(#fff\b|#ffffff\b|white\b)", cuerpo)
            fondo = re.search(r"background(?:-color)?:[^;]*var\(--accent-(?:primary|denim)\)", cuerpo)
            if blanco and fondo:
                sospechosas.append(f"{origen}: {m.group(1).strip()[:60]}")
    assert not sospechosas, sospechosas


def test_los_fondos_con_texto_blanco_que_se_corrigieron_usan_el_token():
    for archivo, fragmentos in {
        "static/css/style.css": (".btn-primary, .btn-denim { background: linear-gradient(135deg, var(--accent-solid),", ".btn-secondary.active {\n    background: var(--accent-solid);", ".rf-limite { background: var(--accent-solid);",
                                 ".chat-msg-user { background: var(--accent-solid);", ".chat-fab { position: fixed;"),
        "static/css/ux.css": (".ux-acciones-titulo .ux-contador { background: var(--accent-solid);", ".ux-periodo-botones .btn.active { background: var(--accent-solid);", ".ux-zona.activa { background: var(--accent-solid);"),
        "static/css/shell.css": (".cuenta-inicial {",),
        "templates/landing.html": (".lp-btn-primario { color: #fff; background: linear-gradient(135deg, var(--accent-solid),", ".lp-plan-badge {"),
        "templates/planes.html": ("background: var(--accent-solid);",),
    }.items():
        texto = _leer(*archivo.split("/"))
        for f in fragmentos:
            assert f in texto, (archivo, f)
    assert "var(--accent-solid)" in _leer("static", "css", "shell.css")


def test_la_marca_del_tema_claro_es_dorado_oscuro_y_no_marron():
    css = _leer("static", "css", "shell.css")
    regla = re.search(r':root\[data-theme="light"\] \.brand-mark \{\s*background:\s*linear-gradient\(135deg,\s*(#[0-9a-f]{6}),\s*(#[0-9a-f]{6})\)', css)
    assert regla, "falta el dorado de la marca para el tema claro"
    for color in regla.groups():
        for fondo in ("#ffffff", "#f4f5f8"):
            assert contraste(color, fondo) >= 3.0, (color, fondo)                  # se ve contra el fondo claro
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert r > g > b and g / r >= 0.65, f"{color} ya no es dorado (se ve marrón)"      # el marrón de antes (#92400e) tiene g/r = 0,43; el dorado, ~0,72
    assert "#92400e" not in regla.group(0)
    # el dorado de TEXTO del tema claro no se toca: sigue llegando a 4,5:1 sobre sus fondos teñidos
    estilo = _leer("static", "css", "style.css")
    assert contraste(_variable(estilo, ':root[data-theme="light"]', "accent-gold"), "#ffffff") >= 4.5

"""
Ola 1 del plan de la beta (2026-10-22): sistema visual. Son pruebas de GUARDA: si alguien vuelve a escribir un tamaño de letra suelto por debajo de 12 px, un color de insignia que no se lee,
una tarjeta de números pintada sin que haya un estado o una grilla que deja una tarjeta sola, falla acá.

  D12/D22  letra: piso de 12 px y tres tamaños chicos con nombre (`--text-2xs/xs/sm`), en vez de 12 valores sueltos;
  D16      el violeta que se usa como TEXTO es `--accent-texto`;
  D17/D18  insignia roja y píldora neutra con texto blanco: 4,5:1 como mínimo;
  D20      la estrella vacía se ve;
  D29/D30  tarjetas de números: color solo con estado y columnas según la cantidad (sin una tarjeta huérfana);
  D32      «Actualizar» deja de ser un botón violeta: dice hace cuánto se actualizó.
"""
import glob
import json
import os
import re
import shutil
import subprocess

import pytest

from tests.test_contraste import CLARO, OSCURO, _rgb, contraste

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
BLANCO = (255, 255, 255)


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


def _archivos_de_estilo():
    """Todo lo que puede llevar un font-size: plantillas, JS propio y el CSS de las pantallas (movil.css lo maneja con su propio piso)."""
    rutas = glob.glob(os.path.join(RAIZ, "templates", "*.html")) + glob.glob(os.path.join(RAIZ, "static", "js", "*.js"))
    rutas += [os.path.join(RAIZ, "static", "css", n) for n in ("style.css", "ux.css", "shell.css", "publico.css")]
    return rutas


# ── Letra ────────────────────────────────────────────────────────────────────────
def test_los_tamanos_chicos_tienen_un_piso_de_12_px_y_se_definen_una_sola_vez():
    css = _leer("static", "css", "style.css")
    for token in ("text-2xs", "text-xs", "text-sm", "text-base"):
        valor = re.search(rf"--{token}:\s*([^;]+);", css).group(1)
        assert valor.startswith("max(12px,"), f"--{token} no tiene piso de 12 px: {valor}"


def test_no_quedan_tamanos_de_letra_sueltos_por_debajo_de_12_px():
    """`font-size: 0.8em` (11,6 px; anidado, menos) y `font-size: 10px` ya no se escriben a mano: se usa var(--text-2xs / --text-xs / --text-sm). Los contadores de las insignias
    (11 px, en negrita) son la única excepción a propósito."""
    sueltos = []
    patron = re.compile(r"font-size:\s*(?:(?<![\d.])0?\.[67]\d*em|(?<![\d.])0?\.8[0-9]?em|(?<![\d.])(?:9|10)(?:\.\d+)?px|0?\.[5-6]\d*rem|0?\.7[0-4]\d*rem)")
    for ruta in _archivos_de_estilo():
        for n, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if patron.search(linea):
                sueltos.append(f"{os.path.relpath(ruta, RAIZ)}:{n}: {linea.strip()[:90]}")
    assert not sueltos, "letra suelta por debajo de 12 px (usar var(--text-xs)): " + " | ".join(sueltos[:6])


def test_los_contadores_de_las_insignias_miden_11_px_no_menos():
    for archivo, selector in (("shell.css", ".subnav-tab-badge"), ("style.css", ".nav-badge")):
        css = _leer("static", "css", archivo)
        if selector in css:
            bloque = css[css.index(selector):css.index("}", css.index(selector))]
            tam = re.search(r"font-size:\s*(\d+)px", bloque)
            assert not tam or int(tam.group(1)) >= 11, (archivo, selector, tam.group(0))


# ── Color ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tema,tokens", (("oscuro", OSCURO), ("claro", CLARO)))
def test_texto_blanco_sobre_la_insignia_roja_y_la_pildora_neutra_se_lee(tema, tokens):
    for fondo in ("danger-solid", "neutral-solid"):
        c = contraste(BLANCO, _rgb(tokens[fondo], tokens))
        assert c >= 4.5, f"blanco sobre --{fondo} ({tema}): {c:.2f}:1"


def test_las_insignias_usan_el_rojo_solido_y_la_pildora_neutra_su_fondo():
    assert "background: var(--danger-solid)" in _leer("static", "css", "shell.css")
    assert "background: var(--danger-solid)" in _leer("static", "css", "style.css")
    assert ".ux-pill.ux-neutral:not(.ux-pill-suave) { background: var(--neutral-solid); }" in _leer("static", "css", "ux.css")


@pytest.mark.parametrize("tema,tokens", (("oscuro", OSCURO), ("claro", CLARO)))
def test_la_estrella_vacia_se_ve(tema, tokens):
    css = _leer("static", "css", "ux.css")
    assert ".ux-estrellas span { color: var(--text-faint); }" in css
    tarjeta = _rgb(tokens["bg-surface"], tokens)
    assert contraste(_rgb(tokens["text-faint"], tokens), tarjeta) >= 3.0, tema


def test_el_violeta_de_los_textos_es_el_de_texto():
    """Un violeta pensado para fondos y bordes (`--accent-primary`) no se usa como color de un texto de la navegación, de un link o de una etiqueta."""
    for archivo, fragmento in (("shell.css", ".bottombar-item.active { color: var(--accent-texto); }"), ("publico.css", ".lg-articulo a { color: var(--accent-texto); }"),
                               ("ux.css", ".flex-ver summary { cursor: pointer; color: var(--accent-texto);")):
        assert fragmento in _leer("static", "css", archivo)
    assert ".menu-lateral-item.active { color: var(--accent-texto); }" in _leer("templates", "base.html")


# ── Tarjetas de números ─────────────────────────────────────────────────────────
def test_una_tarjeta_de_numeros_solo_se_pinta_cuando_hay_estado():
    ux = _leer("static", "css", "ux.css")
    assert ".ux-kpi:not(.ux-ok):not(.ux-warn):not(.ux-danger) { --ux-c: var(--text-secondary); border-top-color: var(--glass-border); }" in ux
    assert ".ux-kpi:not(.ux-ok):not(.ux-warn):not(.ux-danger) .ux-kpi-valor { color: var(--text-primary); }" in ux


def test_las_grillas_de_tarjetas_se_reparten_segun_cuantas_hay():
    """3 → 3 · 4 → 2×2 (4 desde 1000 px) · 5 → 3 + 2 a todo el ancho (5 desde 1180 px) · 6 → 3×2 (6 desde 1280 px): nunca una tarjeta sola en la segunda fila."""
    ux = _leer("static", "css", "ux.css")
    for n, columnas in ((3, 3), (4, 2), (5, 6), (6, 3)):
        assert re.search(rf"\.ux-kpis:has\(> :nth-child\({n}\):last-child\) \{{ grid-template-columns: repeat\({columnas}, minmax\(0, 1fr\)\); \}}", ux), n
    assert re.search(r"min-width: 1000px\) \{\s*\.ux-kpis:has\(> :nth-child\(4\):last-child\) \{ grid-template-columns: repeat\(4,", ux)
    assert re.search(r"min-width: 1180px\) \{\s*\.ux-kpis:has\(> :nth-child\(5\):last-child\) \{ grid-template-columns: repeat\(5,", ux)
    assert re.search(r"min-width: 1280px\) \{\s*\.ux-kpis:has\(> :nth-child\(6\):last-child\) \{ grid-template-columns: repeat\(6,", ux)
    assert "grid-column: span 2" in ux and "grid-column: span 3" in ux          # el 3 + 2 reparte las dos de abajo a todo el ancho


# ── «Actualizar» ────────────────────────────────────────────────────────────────
def test_el_boton_de_actualizar_ya_no_es_violeta():
    boton = re.search(r'<button[^>]*id="btn-sincronizar-todo"[^>]*>', _leer("templates", "base.html")).group(0)
    assert "btn-secondary" in boton and "btn-denim" not in boton and "btn-primary" not in boton
    assert 'aria-label="Actualizar con Mercado Libre"' in boton                      # el nombre accesible sigue diciendo qué hace


def _texto_hace_con_node(tmp_path, segundos):
    js = _leer("static", "js", "global.js")
    fn = re.search(r"function _textoHace\(segundos\) \{.*?\n\}\n", js, re.S).group(0)
    guion = tmp_path / "hace.js"
    guion.write_text(fn + f"\nconsole.log(JSON.stringify({json.dumps(segundos)}.map(_textoHace)));", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:400]
    return json.loads(r.stdout)


@CON_NODE
def test_el_boton_dice_hace_cuanto_se_actualizo(tmp_path):
    assert _texto_hace_con_node(tmp_path, [0, 45, 89, 90, 240, 3540, 3600, 7200, 86400, 129600, 172800, 864000]) == [
        "hace un momento", "hace un momento", "hace un momento", "hace 2 min", "hace 4 min", "hace 59 min", "hace 1 h", "hace 2 h", "hace 24 h", "hace 2 d", "hace 2 d", "hace 10 d"]


def test_el_ticker_trae_hace_cuanto_se_sincronizo_y_el_navegador_lo_usa():
    assert '"sync_hace_segundos": sync_hace_segundos' in _leer("dashboard.py")
    js = _leer("static", "js", "global.js")
    assert "_recordarSincronizacion(data.sync_hace_segundos)" in js and "_recordarSincronizacion(0)" in js      # al cargar la barra y al terminar una sincronización
    assert "Actualizado ${hace}" in js                                                                           # el detalle completo va en el tooltip; el botón dice solo «Hace 8 min»

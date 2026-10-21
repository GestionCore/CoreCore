"""
Correcciones chicas de diseño de la auditoría del 2026-10-21 (`docs/AUDITORIA_DISENO_100.md`), cada una con su guarda para que no vuelva:
· D40 CSS muerto de `#fondo-particulas` (el canvas ya no se incluye)  · D41 `transition: all` (anima también ancho y alto)  · D19 contador gris dentro de un botón (1,65:1 sobre violeta)
· D60 el valor de ejemplo de la Calculadora en negrita 800 se leía como un valor cargado  · D78 el diálogo de confirmación sin nombre  · D47 las páginas de error sin la tipografía de la marca.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


def test_el_css_no_tiene_restos_del_fondo_de_particulas_ni_transition_all():
    for nombre in ("style.css", "ux.css", "shell.css", "movil.css"):
        css = _leer("static", "css", nombre)
        assert "fondo-particulas" not in css, nombre
        assert not re.search(r"transition:\s*all\b", css), f"{nombre}: transition: all anima también ancho y alto; listar las propiedades"


def test_la_plantilla_base_no_incluye_el_canvas_de_particulas():
    assert "fondo-particulas" not in _leer("templates", "base.html")


def test_el_contador_dentro_de_un_boton_toma_el_color_del_boton():
    css = _leer("static", "css", "style.css")
    assert re.search(r"\.btn \.text-muted\s*\{\s*color:\s*inherit;", css)


def test_el_valor_de_ejemplo_del_campo_grande_no_va_en_negrita():
    css = _leer("static", "css", "ux.css")
    assert re.search(r"\.ux-input-grande::placeholder\s*\{\s*font-weight:\s*400;", css)


def test_el_dialogo_de_confirmacion_tiene_nombre_accesible():
    html = _leer("templates", "base.html")
    dialogo = re.search(r'<div id="modal-confirmar"[^>]*>', html).group(0)
    assert 'aria-labelledby="modal-confirmar-texto"' in dialogo
    assert 'id="modal-confirmar-texto"' in html


def test_la_pagina_de_error_carga_la_tipografia_de_la_marca():
    import app as modulo_app
    r = modulo_app.app.test_client().get("/esta-pagina-no-existe-123")
    assert r.status_code == 404
    assert "/static/css/fonts.css?v=" in r.get_data(as_text=True)


def test_los_chips_y_botones_chicos_del_celular_miden_44_px():
    """D49/D50: medido en un navegador a 375 px, estos medían 37 (chips de Día a día), 32 (búsquedas de Tendencias), 29 (series del Monitor) y 20 px (ordenar tablas)."""
    css = _leer("static", "css", "movil.css")
    regla = re.search(r"([^{}]+)\{\s*min-height:\s*44px;\s*display:\s*inline-flex;\s*align-items:\s*center;\s*\}", css)
    assert regla, "falta la regla de 44 px para los chips"
    for selector in (".dia-resumen-item", ".ux-chip-serie", "button.badge", ".th-orden"):
        assert selector in regla.group(1), selector

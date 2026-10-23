"""
Modo privacidad (static/js/privacidad.js): tapa TODO texto con un monto en pesos. Antes una lista fija de clases dejaba a la vista 48 de los 57 montos del Dashboard (la píldora de la barra,
las tarjetas «Facturado − Costos = Te queda», el texto del hero, el detalle de cada misión…), medido en el navegador. La lógica corre de verdad con node sobre un DOM mínimo.
"""
import json
import os
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _node(codigo, tmp_path):
    ruta = os.path.join(RAIZ, "static", "js", "privacidad.js").replace("\\", "/")
    guion = tmp_path / "prueba.js"
    guion.write_text(f"const P = require({json.dumps(ruta)});\n{codigo}", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


# Un DOM de mentira: cada elemento tiene su texto, su clase y si cae dentro de algo que se excluye (un <script>, un campo…)
_DOM = """
function elemento(nombre, excluido) { const clases = new Set(); return { nombre, classList: { add: (c) => clases.add(c), contains: (c) => clases.has(c) }, closest: () => excluido ? {} : null, clases }; }
function documentoCon(items) { return { createTreeWalker: () => { let i = -1; return { nextNode() { i++; return i < items.length; }, get currentNode() { return { nodeValue: items[i].texto, parentElement: items[i].el }; } }; } }; }
"""


@CON_NODE
def test_reconoce_un_monto_en_pesos_o_en_dolares_y_nada_mas(tmp_path):
    casos = ["$28.080", "Hoy: 1 venta · $53.349", "Llevás $28.080 de ganancia", "US$ 1.200", "$ 500", "Pasaste de $3.978.797 a $2.502.068", "28.080", "10 unidades", "Precio en $", "", None]
    r = _node(f"console.log(JSON.stringify({json.dumps(casos)}.map(P.tieneMonto)))", tmp_path)
    assert r == [True, True, True, True, True, True, False, False, False, False, False]


@CON_NODE
def test_marca_cada_elemento_con_un_monto_y_deja_el_resto(tmp_path):
    r = _node(_DOM + """
      const monto = elemento('b'), frase = elemento('span'), titulo = elemento('h1'), guion = elemento('script', true), campo = elemento('input', true);
      const doc = documentoCon([{texto: '$28.080', el: monto}, {texto: 'Hoy: 1 venta · $53.349', el: frase}, {texto: 'Dashboard', el: titulo}, {texto: 'var x = "$5"', el: guion}, {texto: '$100', el: campo}]);
      const cuantos = P.marcar({}, doc);
      console.log(JSON.stringify({cuantos, monto: monto.clases.has('monto-oculto'), frase: frase.clases.has('monto-oculto'), titulo: titulo.clases.has('monto-oculto'), guion: guion.clases.has('monto-oculto'), campo: campo.clases.has('monto-oculto')}));
    """, tmp_path)
    assert r == {"cuantos": 2, "monto": True, "frase": True, "titulo": False, "guion": False, "campo": False}


@CON_NODE
def test_volver_a_marcar_no_cuenta_dos_veces_lo_ya_marcado(tmp_path):
    r = _node(_DOM + """
      const a = elemento('b');
      const doc = documentoCon([{texto: '$1', el: a}, {texto: '$2', el: a}]);       // el mismo elemento con dos textos con monto
      console.log(JSON.stringify([P.marcar({}, doc), P.marcar({}, doc)]));
    """, tmp_path)
    assert r == [1, 0]


@CON_NODE
def test_una_raiz_vacia_o_sin_documento_no_rompe(tmp_path):
    assert _node("console.log(JSON.stringify([P.marcar(null), P.marcar({}, null)]))", tmp_path) == [0, 0]


def test_la_pagina_carga_el_script_antes_de_global_js_y_global_js_lo_usa():
    base = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    global_js = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    assert base.index("js/privacidad.js") < base.index("js/global.js")
    assert "Privacidad.alternar()" in global_js and "classList.toggle('modo-privacidad')" not in global_js


def test_el_css_desenfoca_lo_marcado_y_lo_deja_ver_al_pasar_el_mouse():
    css = open(os.path.join(RAIZ, "static", "css", "ux.css"), encoding="utf-8").read()
    assert "html.modo-privacidad .monto-oculto { filter: blur(" in css and "html.modo-privacidad .monto-oculto:hover { filter: none; }" in css


def test_los_graficos_tambien_se_desenfocan_con_el_modo_privacidad():
    """Los ejes y el detalle de un gráfico («$12.000.000») viven en un canvas: el recorrido de texto no los ve, así que lo tapa el CSS (D7)."""
    css = open(os.path.join(RAIZ, "static", "css", "ux.css"), encoding="utf-8").read()
    assert "html.modo-privacidad canvas { filter: blur(" in css and "html.modo-privacidad canvas:hover { filter: none; }" in css

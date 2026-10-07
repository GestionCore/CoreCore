"""
Tablas que se ordenan por columna (static/js/tablas.js). La lógica de ordenar se ejecuta de verdad con node; el HTML se revisa leyendo las plantillas.
"""
import glob
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTILLAS = sorted(glob.glob(os.path.join(RAIZ, "templates", "*.html")))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _node(codigo, tmp_path):
    """Corre `codigo` con las funciones de tablas.js a mano (T) y devuelve lo que imprima como JSON. El script va a un archivo UTF-8 y la salida se lee como UTF-8:
    en Windows, por la línea de comandos y con el idioma del sistema, los acentos llegaban cambiados."""
    ruta = os.path.join(RAIZ, "static", "js", "tablas.js").replace("\\", "/")
    guion = tmp_path / "prueba.js"
    guion.write_text(f"const T = require({json.dumps(ruta)});\n{codigo}", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


@CON_NODE
def test_los_numeros_se_leen_con_el_formato_argentino(tmp_path):
    casos = ["$1.234.567", "-$1.234", "$-1.234", "12,5%", "1.234,50", "4 u.", "~14 días", "—", "", "sin dato", "$0"]
    valores = _node(f"console.log(JSON.stringify({json.dumps(casos)}.map(T.valorNumerico)))", tmp_path)
    assert valores == [1234567, -1234, -1234, 12.5, 1234.5, 4, 14, None, None, None, 0]


@CON_NODE
def test_los_vacios_van_siempre_al_final_en_cualquier_sentido(tmp_path):
    r = _node("""
      const g = [{valor: 5, original: 0}, {valor: null, original: 1}, {valor: 9, original: 2}, {valor: 1, original: 3}];
      const ids = (sentido) => T.ordenarGrupos(g, 'num', sentido).map(x => x.original);
      console.log(JSON.stringify({asc: ids('asc'), desc: ids('desc'), original: ids(null)}));
    """, tmp_path)
    assert r == {"asc": [3, 0, 2, 1], "desc": [2, 0, 3, 1], "original": [0, 1, 2, 3]}


@CON_NODE
def test_el_orden_es_estable_con_valores_iguales(tmp_path):
    r = _node("""
      const g = [{valor: 'a', original: 0}, {valor: 'b', original: 1}, {valor: 'a', original: 2}, {valor: 'b', original: 3}];
      console.log(JSON.stringify(T.ordenarGrupos(g, 'texto', 'desc').map(x => x.original)));
    """, tmp_path)
    assert r == [1, 3, 0, 2]


@CON_NODE
def test_los_textos_se_ordenan_sin_acentos_y_con_numeros_naturales(tmp_path):
    r = _node("""
      const v = ['Zapato', 'árbol', 'Remera 10', 'Remera 2', 'Buzo'];
      console.log(JSON.stringify(v.slice().sort((a, b) => T.comparar(a, b, 'texto', 'asc'))));
    """, tmp_path)
    assert r == ["árbol", "Buzo", "Remera 2", "Remera 10", "Zapato"]


@CON_NODE
def test_el_primer_toque_va_de_mayor_a_menor_en_numeros_y_de_la_a_a_la_z_en_textos_y_el_tercero_vuelve_al_original(tmp_path):
    r = _node("""
      const ciclo = (tipo, pref) => { const out = []; let s = null; for (let i = 0; i < 4; i++) { s = T.siguienteSentido(s, tipo, pref); out.push(s); } return out; };
      console.log(JSON.stringify({num: ciclo('num'), texto: ciclo('texto'), fechas: ciclo('texto', 'desc'), urgencia: ciclo('num', 'asc')}));
    """, tmp_path)
    assert r == {"num": ["desc", "asc", None, "desc"], "texto": ["asc", "desc", None, "asc"], "fechas": ["desc", "asc", None, "desc"], "urgencia": ["asc", "desc", None, "asc"]}


def test_tablas_js_se_carga_en_todas_las_pantallas():
    base = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    assert "js/tablas.js" in base and base.index("js/global.js") < base.index("js/tablas.js")


def test_cada_tabla_ordenable_declara_columnas_con_un_tipo_valido():
    for ruta in PLANTILLAS:
        html = open(ruta, encoding="utf-8").read()
        for tabla in re.findall(r"<table[^>]*data-ordenable[^>]*>.*?</thead>", html, flags=re.S):
            tipos = re.findall(r"<th[^>]*\bdata-orden=\"([^\"]*)\"", tabla)
            assert tipos, f"{os.path.basename(ruta)}: una tabla data-ordenable sin ninguna columna data-orden"
            assert set(tipos) <= {"num", "texto"}, f"{os.path.basename(ruta)}: tipo de orden desconocido {set(tipos)}"
            for primero in re.findall(r"data-primero=\"([^\"]*)\"", tabla):
                assert primero in {"asc", "desc"}


def test_los_titulos_de_una_linea_siempre_llevan_el_texto_completo_al_pasar_el_mouse():
    """Un título recortado con «…» sin atributo title no se puede leer entero: es peor que dejarlo en tres líneas."""
    for ruta in PLANTILLAS:
        html = open(ruta, encoding="utf-8").read()
        for etiqueta in re.findall(r"<(?:span|strong|b|div)[^>]*class=\"[^\"]*\btitulo-1l\b[^\"]*\"[^>]*>", html):
            assert "title=" in etiqueta, f"{os.path.basename(ruta)}: {etiqueta}"


@CON_NODE
def test_el_selector_del_celular_nombra_cada_orden_en_castellano(tmp_path):
    r = _node("""
      console.log(JSON.stringify([T.etiquetaDeOrden('num', 'desc'), T.etiquetaDeOrden('num', 'asc'), T.etiquetaDeOrden('texto', 'asc'), T.etiquetaDeOrden('texto', 'desc')]));
    """, tmp_path)
    assert r == ["de mayor a menor", "de menor a mayor", "de la A a la Z", "de la Z a la A"]


def test_el_selector_de_orden_solo_se_ve_en_el_celular():
    css = open(os.path.join(RAIZ, "static", "css", "ux.css"), encoding="utf-8").read()
    assert re.search(r"\.orden-movil\s*\{\s*display:\s*none;\s*\}", css)                                                    # escondido por defecto
    assert re.search(r"@media \(max-width: 720px\)\s*\{\s*\.orden-movil\s*\{\s*display:\s*flex", css)                      # y aparece con el ancho en que la tabla pasa a tarjetas

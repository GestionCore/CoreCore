"""
Stock masivo: al buscar se abren los modelos que coinciden, y al BORRAR la búsqueda tienen que volver a como estaban (antes quedaban abiertos todos los que se encontraron).
Se ejecutan de verdad las funciones de la plantilla con node y un DOM mínimo simulado.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _funciones_de_la_plantilla():
    """El código de abrirItem … filtrarAcordeon tal como está en stock_masivo.html (de `let _estadoAntesDeBuscar` hasta el final de filtrarAcordeon)."""
    src = open(os.path.join(RAIZ, "templates", "stock_masivo.html"), encoding="utf-8").read()
    inicio = src.index("    function abrirItem(item, abrir)")
    fin = src.index("    function alternarSoloEditables()")
    return src[inicio:fin]


PRELUDIO = r"""
class Item {
  constructor(nombre, abierto) {
    this.nombre = nombre; this.dataset = { buscar: nombre.toLowerCase(), editable: '1' }; this.style = {}; this._abierto = abierto;
    this._cuerpo = { style: { display: abierto ? 'block' : 'none' } }; this._cabecera = { setAttribute() {} };
    this.classList = { contains: (c) => c === 'abierto' && this._abierto, toggle: (c, v) => { if (c === 'abierto') this._abierto = v; } };
  }
  querySelector(sel) { return sel === '.acordeon-body' ? this._cuerpo : this._cabecera; }
  closest() { return this; }
  get abierto() { return this._abierto; }
}
const items = [new Item('Campera Negra', false), new Item('Campera Azul', true), new Item('Buzo Gris', false), new Item('Remera Blanca', false)];
const entrada = { value: '' };
const vacio = { style: {} }; const botonTodos = { textContent: '' };
global.document = { getElementById: (id) => id === 'input-buscador-masivo' ? entrada : (id === 'acordeon-sin-resultados' ? vacio : botonTodos),
                    querySelectorAll: () => items };
global.coincideBusqueda = (texto, q) => !q.trim() || texto.includes(q.trim().toLowerCase());
"""


def _node(codigo, tmp_path):
    guion = tmp_path / "prueba.js"
    guion.write_text(PRELUDIO + "\nlet soloEditables = false;\n" + _funciones_de_la_plantilla() + "\n" + codigo, encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_al_borrar_la_busqueda_los_modelos_vuelven_a_como_estaban(tmp_path):
    r = _node("""
      const estado = () => items.map(i => i.abierto);
      const salida = { inicio: estado() };
      entrada.value = 'campera'; filtrarAcordeon();
      salida.buscando = estado();                              // las dos camperas abiertas
      entrada.value = 'camper'; filtrarAcordeon();             // seguir escribiendo no pisa la memoria del estado original
      entrada.value = ''; filtrarAcordeon();
      salida.borrada = estado();
      salida.visibles = items.map(i => i.style.display);
      console.log(JSON.stringify(salida));
    """, tmp_path)
    assert r["inicio"] == [False, True, False, False]
    assert r["buscando"] == [True, True, False, False]
    assert r["borrada"] == [False, True, False, False]                 # la Negra vuelve a plegada, la Azul sigue abierta como antes
    assert r["visibles"] == ["", "", "", ""]


@CON_NODE
def test_lo_que_la_persona_abre_o_cierra_a_mano_durante_la_busqueda_se_respeta(tmp_path):
    r = _node("""
      entrada.value = 'campera'; filtrarAcordeon();
      toggleAcordeon(items[0]);                                // la persona cierra a mano la Negra mientras busca
      toggleAcordeon(items[1]);                                // y la Azul también
      entrada.value = ''; filtrarAcordeon();
      console.log(JSON.stringify(items.map(i => i.abierto)));
    """, tmp_path)
    assert r == [False, False, False, False]                          # no se le devuelve la Azul abierta: lo cerró ella


@CON_NODE
def test_una_busqueda_nueva_despues_de_borrar_arranca_de_cero(tmp_path):
    r = _node("""
      entrada.value = 'buzo'; filtrarAcordeon(); entrada.value = ''; filtrarAcordeon();
      toggleAcordeon(items[3]);                                // sin búsqueda: abre la Remera a mano
      entrada.value = 'campera'; filtrarAcordeon(); entrada.value = ''; filtrarAcordeon();
      console.log(JSON.stringify(items.map(i => i.abierto)));
    """, tmp_path)
    assert r == [False, True, False, True]                            # la Remera abierta a mano antes de buscar sigue abierta


def test_la_plantilla_tiene_la_memoria_del_estado_previo():
    src = _funciones_de_la_plantilla()
    assert "_estadoAntesDeBuscar" in src and re.search(r"function toggleAcordeon", src)

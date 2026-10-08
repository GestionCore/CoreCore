"""
Los paneles modales (cajón de publicación, menú lateral, comentarios, buscador, confirmaciones) atrapan el foco con Tab y lo devuelven a quien los abrió (ux.js: UX.atraparFoco / soltarFoco).
La lógica de la pila y del ciclo se ejecuta de verdad con node; que cada panel la use y tenga role="dialog" se revisa en las plantillas. Verificado además en un navegador real (2026-10-08).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")

PRELUDIO = r"""
const registro = [];
class Elemento {
  constructor(nombre, hijos = []) { this.nombre = nombre; this.hijos = hijos; this.attrs = {}; this.disabled = false; this.offsetParent = {}; }
  hasAttribute(a) { return a in this.attrs; } setAttribute(a, v) { this.attrs[a] = v; }
  focus() { global.document.activeElement = this; registro.push('foco:' + this.nombre); }
  contains(x) { return x === this || this.hijos.some(h => h.contains && h.contains(x)); }
  querySelectorAll() { return this.hijos.filter(h => !h.disabled); }
}
const oyentes = {};
global.window = { addEventListener() {}, MutationObserver: undefined };
global.document = { addEventListener: (t, f) => { (oyentes[t] = oyentes[t] || []).push(f); }, querySelectorAll() { return []; }, documentElement: {}, body: new Elemento('body'),
                    activeElement: null, contains() { return true; } };
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
function tecla(key, shiftKey) { const e = { key, shiftKey: !!shiftKey, prevented: false, preventDefault() { this.prevented = true; } }; (oyentes.keydown || []).forEach(f => f(e)); return e; }
"""


def _node(codigo, tmp_path):
    ruta = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "prueba.js"
    guion.write_text(PRELUDIO + f"const fs = require('fs'); eval(fs.readFileSync({json.dumps(ruta)}, 'utf8') + '\\n;global.UX = UX;');\n{codigo}", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_tab_da_la_vuelta_dentro_del_panel_y_el_foco_vuelve_al_cerrar(tmp_path):
    r = _node("""
      const a = new Elemento('a'), b = new Elemento('b'), c = new Elemento('c');
      const panel = new Elemento('panel', [a, b, c]);
      const abridor = new Elemento('abridor'); abridor.focus();
      UX.atraparFoco(panel);
      const salida = { focoEntra: document.activeElement === panel, tabindex: panel.attrs.tabindex };
      c.focus(); const e1 = tecla('Tab'); salida.deUltimoAPrimero = document.activeElement === a && e1.prevented;
      a.focus(); const e2 = tecla('Tab', true); salida.deMayusAlUltimo = document.activeElement === c && e2.prevented;
      b.focus(); const e3 = tecla('Tab'); salida.enElMedioNoInterviene = e3.prevented === false;
      abridor.focus(); tecla('Tab'); salida.siEstabaAfueraLoMetenAdentro = document.activeElement === a;
      UX.soltarFoco(panel); salida.volvioAlAbridor = document.activeElement === abridor;
      const e4 = tecla('Tab'); salida.sinPanelNoInterviene = e4.prevented === false;
      console.log(JSON.stringify(salida));
    """, tmp_path)
    assert r == {"focoEntra": True, "tabindex": "-1", "deUltimoAPrimero": True, "deMayusAlUltimo": True, "enElMedioNoInterviene": True, "siEstabaAfueraLoMetenAdentro": True,
                 "volvioAlAbridor": True, "sinPanelNoInterviene": True}


@CON_NODE
def test_con_dos_paneles_uno_encima_del_otro_manda_el_de_arriba_y_cada_uno_devuelve_su_foco(tmp_path):
    r = _node("""
      const a1 = new Elemento('a1'), a2 = new Elemento('a2'), b1 = new Elemento('b1'), b2 = new Elemento('b2');
      const abajo = new Elemento('abajo', [a1, a2]), arriba = new Elemento('arriba', [b1, b2]);
      const abridor = new Elemento('abridor'); abridor.focus();
      UX.atraparFoco(abajo); a2.focus();
      UX.atraparFoco(arriba);                                   // el de arriba se abre desde el de abajo
      b2.focus(); tecla('Tab'); const cicloEnElDeArriba = document.activeElement === b1;
      UX.soltarFoco(arriba); const volvioAlDeAbajo = document.activeElement === a2;
      a2.focus(); tecla('Tab'); const ahoraManda_ElDeAbajo = document.activeElement === a1;
      UX.soltarFoco(abajo);
      console.log(JSON.stringify({ cicloEnElDeArriba, volvioAlDeAbajo, ahoraManda_ElDeAbajo, alFinalAlAbridor: document.activeElement === abridor }));
    """, tmp_path)
    assert all(r.values()), r


@CON_NODE
def test_atrapar_dos_veces_el_mismo_panel_o_soltar_uno_que_no_esta_no_rompe(tmp_path):
    r = _node("""
      const x = new Elemento('x'), panel = new Elemento('panel', [x]), otro = new Elemento('otro');
      const abridor = new Elemento('abridor'); abridor.focus();
      UX.atraparFoco(panel); UX.atraparFoco(panel); UX.atraparFoco(null); UX.soltarFoco(otro); UX.soltarFoco(null);
      UX.soltarFoco(panel);
      console.log(JSON.stringify({ volvio: document.activeElement === abridor, soloUnFocoDeEntrada: registro.filter(f => f === 'foco:panel').length }));
    """, tmp_path)
    assert r == {"volvio": True, "soloUnFocoDeEntrada": 1}


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


def test_cada_panel_modal_tiene_role_dialog_y_usa_la_trampa_de_foco():
    base, global_js = _leer("templates", "base.html"), _leer("static", "js", "global.js")
    for fragmento in ('class="drawer-panel" role="dialog" aria-modal="true"', 'id="menu-lateral-panel" role="dialog" aria-modal="true"',
                      'class="fb-caja" role="dialog" aria-modal="true"', 'class="command-modal" role="dialog" aria-modal="true"', 'id="modal-confirmar" role="dialog" aria-modal="true"'):
        assert fragmento in base, fragmento
    assert "UX.atraparFoco(document.querySelector('#drawer-overlay .drawer-panel'))" in global_js and "UX.soltarFoco(document.querySelector('#drawer-overlay .drawer-panel'))" in global_js
    assert "UX.atraparFoco(document.getElementById('menu-lateral-panel'))" in base and "UX.soltarFoco(document.getElementById('menu-lateral-panel'))" in base
    assert "UX.atraparFoco(overlay().querySelector('.fb-caja'))" in base and "UX.soltarFoco(overlay().querySelector('.fb-caja'))" in base


def test_el_anillo_de_foco_no_se_dibuja_alrededor_del_panel_entero():
    assert re.search(r"\.drawer-panel:focus[^{]*\{ outline: none; \}", _leer("static", "css", "style.css"))

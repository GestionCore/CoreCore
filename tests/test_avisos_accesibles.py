"""
Avisos (mostrarToast en static/js/global.js): se anuncian a los lectores de pantalla, duran según su largo (antes 3,2 s fijos aunque fuera un error largo), un error se queda hasta cerrarlo
y nunca hay más de 3 a la vez. Se ejecuta la función real con node y un documento mínimo simulado.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Sin node")


def _funcion(fuente, nombre):
    i = fuente.index(f"function {nombre}(")
    j = fuente.index("{", i)
    prof = 0
    for k in range(j, len(fuente)):
        prof += fuente[k] == "{"
        prof -= fuente[k] == "}"
        if prof == 0:
            return fuente[i:k + 1]


def _correr(casos_js):
    fuente = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    toast = _funcion(fuente, "mostrarToast")
    maximos = re.search(r"const TOASTS_MAXIMOS = \d+;", fuente).group(0)
    programa = r"""
const timers = [];
global.setTimeout = (f, ms) => { const t = {f, ms, activo: true}; timers.push(t); return t; };
global.clearTimeout = (t) => { if (t) t.activo = false; };
global.requestAnimationFrame = (f) => f();
const sonidos = [];
global.sonidoExito = () => sonidos.push('exito'); global.sonidoError = () => sonidos.push('error');
function nodo(tag) {
  const n = { tag, attrs: {}, hijos: [], clases: new Set(), oyentes: {}, texto: '', removido: false,
    set className(v) { this.clases = new Set(v.split(' ')); }, get className() { return [...this.clases].join(' '); },
    classList: { add: (c) => n.clases.add(c), remove: (c) => n.clases.delete(c), contains: (c) => n.clases.has(c) },
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(e, f) { (this.oyentes[e] = this.oyentes[e] || []).push(f); },
    append(...xs) { xs.forEach((x) => this.hijos.push(x)); }, appendChild(x) { this.hijos.push(x); return x; },
    remove() { this.removido = true; if (this.padre) this.padre.hijos = this.padre.hijos.filter((h) => h !== this); },
    get children() { return this.hijos.filter((h) => h.tag); }, get firstElementChild() { return this.children[0]; },
    set textContent(v) { this.texto = v; }, get textContent() { return this.texto } };
  return n;
}
const contenedor = nodo('div');
const _app = contenedor.appendChild.bind(contenedor);
contenedor.appendChild = (x) => { x.padre = contenedor; return _app(x); };
global.document = { getElementById: () => contenedor, createElement: nodo, createTextNode: (t) => ({ texto: t }) };
""" + maximos + "\n" + toast + "\n" + casos_js
    r = subprocess.run([NODE, "-e", programa], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_un_aviso_comun_se_anuncia_como_status_y_dura_segun_su_largo():
    r = _correr(r"""
mostrarToast('Guardado', 'success');
mostrarToast('x'.repeat(200), 'info');
mostrarToast('Se actualizaron 3 precios y quedaron 2 pendientes de revisar', 'warning');
console.log(JSON.stringify({ roles: contenedor.children.map((t) => t.attrs.role), duraciones: timers.filter((t) => t.ms >= 3000).map((t) => t.ms), sonidos }));
""")
    assert r["roles"] == ["status", "status", "status"]
    assert r["duraciones"] == [4000, 9000, 6100]                 # «Guardado» → 4 s (mínimo); 200 caracteres → 9 s (tope); 60 caracteres → 2,5 s + 60 ms por carácter = 6,1 s
    assert r["sonidos"] == ["exito"]


def test_un_mensaje_corto_dura_al_menos_cuatro_segundos_y_uno_larguisimo_no_pasa_de_nueve():
    r = _correr(r"""
mostrarToast('ok'); mostrarToast('y'.repeat(1000));
console.log(JSON.stringify({ d: timers.filter((t) => t.ms >= 3000).map((t) => t.ms) }));
""")
    assert r["d"] == [4000, 9000]


def test_un_error_se_anuncia_como_alert_no_se_va_solo_y_se_cierra_con_la_x():
    r = _correr(r"""
mostrarToast('No se pudo guardar: Mercado Libre no respondió. Probá de nuevo en un rato.', 'error');
const t = contenedor.children[0];
const boton = t.hijos.find((h) => h.tag === 'button');
const antes = timers.filter((x) => x.activo && x.ms >= 3000).length;
boton.oyentes.click[0]();
console.log(JSON.stringify({ rol: t.attrs.role, temporizadoresDeCierre: antes, etiqueta: boton.attrs['aria-label'], tipo: boton.type, contenedorDespues: contenedor.children.length, sonidos }));
""")
    assert (r["rol"], r["temporizadoresDeCierre"], r["etiqueta"], r["tipo"], r["sonidos"]) == ("alert", 0, "Cerrar aviso", "button", ["error"])
    assert r["contenedorDespues"] == 1                      # la ✕ lo marca para cerrar y programa su retiro del DOM a los 300 ms (la transición de salida)


def test_nunca_hay_mas_de_tres_avisos_a_la_vez():
    r = _correr(r"""
for (let i = 0; i < 7; i++) mostrarToast('Error número ' + i, 'error');
console.log(JSON.stringify({ n: contenedor.children.length, textos: contenedor.children.map((t) => t.hijos[0].texto) }));
""")
    assert r["n"] == 3 and r["textos"] == ["Error número 4", "Error número 5", "Error número 6"]       # quedan los más nuevos


def test_pasar_el_mouse_pausa_el_cierre_y_al_salir_vuelve_a_programarlo_en_dos_segundos():
    r = _correr(r"""
mostrarToast('Aviso', 'info');
const t = contenedor.children[0];
const programado = timers[timers.length - 1];
t.oyentes.mouseenter[0]();
const pausado = programado.activo === false;
t.oyentes.mouseleave[0]();
console.log(JSON.stringify({ pausado, nuevoMs: timers[timers.length - 1].ms }));
""")
    assert r == {"pausado": True, "nuevoMs": 2000}


def test_un_valor_que_no_es_texto_no_rompe_el_aviso():
    r = _correr(r"""
mostrarToast(null, 'info'); mostrarToast(undefined); mostrarToast(42, 'success');
console.log(JSON.stringify({ t: contenedor.children.map((t) => t.hijos[0].texto) }));
""")
    assert r["t"] == ["", "", "42"]

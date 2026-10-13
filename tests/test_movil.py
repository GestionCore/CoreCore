"""
Ola 2 del plan de UX (PLAN_UX_200.md): la app en el celular.
  · static/css/movil.css se carga ÚLTIMO y define letra legible, botones de 44 px, campos de 16 px y KPIs de a dos;
  · los ejes de los gráficos se abrevian en pantalla angosta ("$1,3 M" y no "$1.250.000", que se comía el gráfico);
  · la pestaña de la pantalla actual queda centrada en la barra que se desliza;
  · el checklist «Completá tu perfil» arranca plegado en el celular (abierto ocupaba toda la primera pantalla y empujaba la ganancia de hoy).
La lógica de JS se ejecuta de verdad con node; los estilos se revisan en el texto (el recorrido en un navegador de 375 px se hizo a mano el 2026-10-12).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── Estilos ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_movil_css_se_carga_ultimo_para_poder_pisar_a_los_demas():
    base = _leer("templates", "base.html")
    orden = [m for m in re.findall(r"css/(\w+)\.css", base)]
    assert orden[-1] == "movil" and orden.index("movil") > max(orden.index(n) for n in ("style", "ux", "shell"))


def test_en_el_celular_la_letra_base_sube_y_nada_baja_de_12_px():
    css = _leer("static", "css", "movil.css")
    movil = css[css.index("@media (max-width: 720px)"):]
    assert re.search(r"body\s*\{\s*font-size:\s*15\.5px", movil)
    assert "max(12px" in movil                                                  # el piso de las etiquetas, pastillas y leyendas chicas


def test_en_el_celular_los_botones_miden_44_px_y_los_campos_16_px():
    movil = _leer("static", "css", "movil.css")
    assert re.search(r"\.btn[^{]*\{\s*min-height:\s*44px", movil)
    assert re.search(r"select, textarea\s*\{\s*font-size:\s*16px;\s*min-height:\s*44px", movil)     # con menos de 16 px el iPhone hace zoom al enfocar


def test_las_tarjetas_de_numeros_van_de_a_dos_y_le_ganan_a_las_reglas_con_has():
    css = _leer("static", "css", "movil.css")
    assert ".ux-kpis.ux-kpis { grid-template-columns: repeat(2, minmax(0, 1fr))" in css          # doble clase: ux.css tiene `.ux-kpis:has(> :nth-child(5))` con la misma fuerza
    assert ".ux-kpis.ux-kpis > :last-child:nth-child(odd) { grid-column: 1 / -1; }" in css        # una tarjeta suelta ocupa el ancho entero


# ── Ejes de los gráficos ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_los_ejes_de_dinero_de_los_graficos_usan_la_version_abreviada():
    for archivo in ("dashboard_personalizable.html", "metricas.html", "publicidad.html"):
        texto = _leer("templates", archivo)
        ejes = re.findall(r"ticks:\s*\{[^}]*callback:\s*\(?v\)?\s*=>\s*UX\.plata\w*\(v\)", texto)
        assert ejes and all("UX.plataEje(v)" in e for e in ejes), (archivo, ejes)


def _ux(codigo, tmp_path, ancho):
    ruta = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "movil_prueba.js"
    guion.write_text("""
const fs = require('fs'), vm = require('vm');
const caja = { console, document: { addEventListener() {}, querySelectorAll: () => [] }, innerWidth: %d };
caja.window = caja; caja.addEventListener = () => {};
vm.createContext(caja);
vm.runInContext(fs.readFileSync(%s, 'utf8') + ';this.UX = UX;', caja);
const UX = caja.UX;
%s
""" % (ancho, json.dumps(ruta), codigo), encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_en_pantalla_angosta_el_eje_se_abrevia_y_en_ancha_muestra_el_monto_entero(tmp_path):
    angosta = _ux("console.log(JSON.stringify([0, 500, 999, 1000, 8500, 850000, 1250000, 10000000, -2500000, null].map(UX.plataEje)));", tmp_path, 375)
    assert angosta == ["$0", "$500", "$999", "$1 mil", "$8,5 mil", "$850 mil", "$1,3 M", "$10 M", "-$2,5 M", "—"]
    ancha = _ux("console.log(JSON.stringify([850000, 1250000, -2500000].map(UX.plataEje)));", tmp_path, 1280)
    assert ancha == ["$850.000", "$1.250.000", "-$2.500.000"]


# ── Pestaña activa centrada ─────────────────────────────────────────────────────────────────────────────────────────────────

@CON_NODE
def test_la_pestana_activa_queda_en_el_centro_de_la_barra_que_se_desliza(tmp_path):
    r = _ux("""
const barra = (scrollWidth, clientWidth, activa) => ({ scrollWidth, clientWidth, scrollLeft: 0, querySelector: () => activa });
const a = barra(900, 375, { offsetLeft: 600, offsetWidth: 100 });                     // la activa está lejos, a la derecha: queda centrada (600 − (375 − 100) / 2)
const b = barra(300, 375, { offsetLeft: 100, offsetWidth: 80 });                      // todo entra: no se mueve
const c = barra(900, 375, null);                                                       // ninguna activa: no se mueve
[a, b, c].forEach(x => UX.centrarActiva(x));
console.log(JSON.stringify([a.scrollLeft, b.scrollLeft, c.scrollLeft]));
""", tmp_path, 375)
    assert r == [462.5, 0, 0]


# ── Checklist plegado en el celular ─────────────────────────────────────────────────────────────────────────────────────────

def test_el_checklist_de_perfil_arranca_plegado_en_el_celular():
    html = _leer("templates", "dashboard_personalizable.html")
    assert "d.completos / d.total >= 0.5 || window.innerWidth <= 720" in html

"""
Ola 3 (D25): el período de Ganancia Real, Costos y Publicidad se aplica al elegirlo (el segundo día del rango, o 7/14/30 días, este mes, mes pasado), sin un «Ver período» que apretar.
Y el botón del período que está mirando la persona vuelve a quedar marcado: desde que los manejadores salieron del HTML (data-click), el código buscaba `button[onclick^=…]` y no encontraba nada.
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


def test_las_tres_pantallas_con_periodo_lo_aplican_al_elegir_y_ya_no_tienen_ver_periodo():
    for plantilla in ("metricas.html", "costos.html", "publicidad.html"):
        html = _leer("templates", plantilla)
        assert re.search(r'<form action="/(metricas|costos#gastos-negocio|publicidad)" method="GET" class="ux-periodo no-imprimir" data-aplica-al-elegir>', html), plantilla
        assert "Ver período" not in html, plantilla


def test_los_botones_de_periodo_dicen_cual_es_en_data_y_el_codigo_ya_no_busca_onclick():
    macro = _leer("templates", "_ux.html")
    for atributo in ('data-periodo-dias="7"', 'data-periodo-dias="14"', 'data-periodo-dias="30"', 'data-periodo-mes="0"', 'data-periodo-mes="-1"'):
        assert atributo in macro
    js = _leer("static", "js", "global.js")
    assert "button[onclick" not in js and "getAttribute('onclick')" not in js


def _correr_node(tmp_path, cuerpo):
    js = _leer("static", "js", "global.js").replace("\r\n", "\n")
    rango = re.search(r"const RangoFechas = \{.*?\n\};\n", js, re.S).group(0)
    periodo = js[js.index('/** "Este mes"'):js.index("document.addEventListener('DOMContentLoaded', marcarUltimosDiasActivo);")]
    guion = tmp_path / "periodo.js"
    guion.write_text(rango + "\n" + periodo + "\n" + cuerpo, encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


@CON_NODE
def test_elegir_el_segundo_dia_aplica_el_periodo_solo_si_la_pantalla_lo_pide(tmp_path):
    r = _correr_node(tmp_path, """
function armar(aplicaAlElegir) {
  const campos = { fecha_desde: { value: '' }, fecha_hasta: { value: '' } };
  const ventana = { innerHTML: '' }, boton = { textContent: '' };
  const estado = { enviados: 0 };
  const form = { hasAttribute: (n) => aplicaAlElegir && n === 'data-aplica-al-elegir', submit: () => { estado.enviados++; } };
  const cont = { dataset: { desde: '2026-10-01', hasta: '2026-10-10' }, classList: { add() {}, remove() {} }, appendChild() {}, closest: () => form,
    querySelector: (s) => s.includes('fecha_desde') ? campos.fecha_desde : s.includes('fecha_hasta') ? campos.fecha_hasta : s === '.rango-fechas-popup' ? ventana : s === '.rango-fechas-boton' ? boton : null };
  global.document = { getElementById: () => cont, createElement: () => ventana, addEventListener() {} };
  RangoFechas.inicializar('x');
  return { campos, estado };
}
const con = armar(true);
RangoFechas.elegirDia('x', '2026-10-12');                    // el primer día de un rango nuevo: todavía no hay período
const tras1 = con.estado.enviados;
RangoFechas.elegirDia('x', '2026-10-15');                    // el segundo: el período queda completo y se aplica
const sin = armar(false);
RangoFechas.elegirDia('x', '2026-10-12'); RangoFechas.elegirDia('x', '2026-10-15');
console.log(JSON.stringify({ tras1, tras2: con.estado.enviados, desde: con.campos.fecha_desde.value, hasta: con.campos.fecha_hasta.value, sinAtributo: sin.estado.enviados }));
""")
    assert r == {"tras1": 0, "tras2": 1, "desde": "2026-10-12", "hasta": "2026-10-15", "sinAtributo": 0}          # una pantalla sin el atributo (Promociones, fechas de un descuento) NO envía nada


@CON_NODE
def test_el_boton_del_periodo_que_se_mira_queda_marcado(tmp_path):
    r = _correr_node(tmp_path, """
const RealDate = Date, FIJO = new RealDate(2026, 9, 22, 10, 0, 0).getTime();               // hoy es siempre el 22/10/2026: el resultado no depende del día en que se corra la prueba
global.Date = class extends RealDate { constructor(...a) { if (a.length) super(...a); else super(FIJO); } static now() { return FIJO; } };
const aISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function botones(lista, atributo) { return lista.map(v => { const b = { dataset: { [atributo]: String(v) }, activo: null }; b.classList = { toggle(c, on) { b.activo = on; } }; return b; }); }
function pantalla(desde, hasta) {
  const dias = botones([7, 14, 30], 'periodoDias'), meses = botones([0, -1], 'periodoMes');
  const form = { querySelectorAll: (s) => s.includes('periodo-dias') ? dias : (s.includes('periodo-mes') ? meses : []) };
  const cont = { dataset: { desde, hasta }, closest: () => form };
  global.document = { querySelectorAll: () => [cont] };
  marcarUltimosDiasActivo();
  return { dias: dias.map(b => b.activo), meses: meses.map(b => b.activo) };
}
const hoy = new Date(); const hace = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return aISO(d); };
const ultimos7 = pantalla(hace(6), aISO(hoy));
const ultimos30 = pantalla(hace(29), aISO(hoy));
const mesCompleto = pantalla(aISO(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)), aISO(new Date(hoy.getFullYear(), hoy.getMonth(), 0)));
const propio = pantalla('2020-01-01', '2020-01-09');
console.log(JSON.stringify({ ultimos7, ultimos30, mesCompleto, propio }));
""")
    assert r["ultimos7"] == {"dias": [True, False, False], "meses": [False, False]}
    assert r["ultimos30"]["dias"] == [False, False, True]
    assert r["mesCompleto"] == {"dias": [False, False, False], "meses": [False, True]}                 # el mes pasado se marca como mes, no como «30 días»
    assert r["propio"] == {"dias": [False, False, False], "meses": [False, False]}                     # un rango propio no marca ningún botón

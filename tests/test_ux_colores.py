"""
Gráficos y cambio de tema (static/js/ux.js): al cambiar data-theme se recolorean los gráficos ya dibujados (Chart.js lee los colores una sola vez al crearlos). La lógica se ejecuta
de verdad con node, con un navegador mínimo simulado; verificada además en un navegador real el 2026-10-08 (los seis colores de un gráfico pasan de oscuro a claro y vuelven).
"""
import json
import os
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")

PRELUDIO = """
const estilos = {};                                           // tokens del tema actual (los mueve cada prueba)
global.window = { addEventListener() {}, MutationObserver: undefined };
global.document = { addEventListener() {}, querySelectorAll() { return []; }, documentElement: {}, body: {} };
global.getComputedStyle = () => ({ getPropertyValue: (t) => estilos[t] || '' });
"""


def _node(codigo, tmp_path):
    ruta = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "prueba.js"
    # ux.js declara `const UX = ...` en el ámbito global de un script: se lo evalúa y se lo expone
    guion.write_text(PRELUDIO + f"const fs = require('fs'); eval(fs.readFileSync({json.dumps(ruta)}, 'utf8') + '\\n;global.UX = UX;');\n{codigo}", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_los_formatos_de_color_se_leen(tmp_path):
    r = _node("""console.log(JSON.stringify(['#8b5cf6', '#fff', 'rgb(1, 2, 3)', 'rgba(255,255,255,0.06)', 'rgba(0 0 0 / 50%)', '#8b5cf680', 'basura', '', null].map(UX.colorARgba)));""", tmp_path)
    assert r[0] == [139, 92, 246, 1]
    assert r[1] == [255, 255, 255, 1]
    assert r[2] == [1, 2, 3, 1]
    assert r[3] == [255, 255, 255, 0.06]
    assert r[4] == [0, 0, 0, 0.5]
    assert r[5][:3] == [139, 92, 246] and abs(r[5][3] - 128 / 255) < 1e-9
    assert r[6:] == [None, None, None]


@CON_NODE
def test_un_gráfico_pasa_de_oscuro_a_claro_y_vuelve(tmp_path):
    r = _node("""
      const OSC = {'--accent-primary': '#8b5cf6', '--success': '#22c55e', '--text-secondary': '#94a3b8', '--border-soft': 'rgba(255, 255, 255, 0.06)'};
      const CLA = {'--accent-primary': '#8b3ffc', '--success': '#059669', '--text-secondary': '#55556e', '--border-soft': 'rgba(0, 0, 0, 0.07)'};
      const config = {
        data: { datasets: [{ borderColor: '#8b5cf6', backgroundColor: 'rgba(139, 92, 246, 0.35)', pointBackgroundColor: '#22c55e', data: [1, 2, 3] }] },
        options: { scales: Object.assign(Object.create(null), { x: Object.assign(Object.create(null), { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255, 255, 255, 0.06)' } }) }) },   // Chart.js arma objetos sin prototipo
      };
      const gradiente = {};  // un CanvasGradient no es un objeto plano: no se toca
      Object.setPrototypeOf(gradiente, { addColorStop() {} });
      config.data.datasets[0].gradiente = gradiente;
      const foto = () => ({ linea: config.data.datasets[0].borderColor, relleno: config.data.datasets[0].backgroundColor, punto: config.data.datasets[0].pointBackgroundColor,
                            tick: config.options.scales.x.ticks.color, grilla: config.options.scales.x.grid.color });
      const salida = { oscuro: foto() };
      const cambios = UX.recolorear(config.data, OSC, CLA) + UX.recolorear(config.options, OSC, CLA);
      salida.cambios = cambios; salida.claro = foto();
      UX.recolorear(config.data, CLA, OSC); UX.recolorear(config.options, CLA, OSC);
      salida.devuelta = foto();
      salida.gradienteIntacto = config.data.datasets[0].gradiente === gradiente;
      console.log(JSON.stringify(salida));
    """, tmp_path)
    assert r["cambios"] == 5
    assert r["claro"] == {"linea": "rgb(139, 63, 252)", "relleno": "rgba(139, 63, 252, 0.35)", "punto": "rgb(5, 150, 105)", "tick": "rgb(85, 85, 110)", "grilla": "rgba(0, 0, 0, 0.07)"}
    # al volver quedan los mismos colores (en otro formato de texto: rgb() en lugar de #hex)
    assert r["devuelta"] == {"linea": "rgb(139, 92, 246)", "relleno": "rgba(139, 92, 246, 0.35)", "punto": "rgb(34, 197, 94)", "tick": "rgb(148, 163, 184)", "grilla": "rgba(255, 255, 255, 0.06)"}
    assert r["gradienteIntacto"] is True


@CON_NODE
def test_un_color_que_no_es_de_ningun_token_no_se_toca_y_alfa_sale_del_tema_actual(tmp_path):
    r = _node("""
      estilos['--accent-primary'] = '#8b3ffc';
      const config = { data: { datasets: [{ borderColor: '#123456', backgroundColor: ['#abcdef', 'rgba(1, 2, 3, 0.4)'] }] } };
      const antes = {'--accent-primary': '#8b5cf6'}, despues = {'--accent-primary': '#8b3ffc'};
      const cambios = UX.recolorear(config.data, antes, despues);
      console.log(JSON.stringify({ cambios, color: config.data.datasets[0], alfa: UX.alfa('--accent-primary', 0.35), alfaRespaldo: UX.alfa('--no-existe', 0.5) }));
    """, tmp_path)
    assert r["cambios"] == 0 and r["color"]["borderColor"] == "#123456"
    assert r["alfa"] == "rgba(139, 63, 252, 0.35)"                                   # el violeta del tema CLARO, no el fijo del oscuro
    assert r["alfaRespaldo"] == "rgba(139, 92, 246, 0.5)"


def test_ningun_grafico_escribe_el_violeta_a_mano():
    """El violeta cambia entre temas (#8b5cf6 oscuro, #8b3ffc claro): en los gráficos se lee del token con UX.alfa()."""
    for rel in ("templates/dashboard_personalizable.html", "templates/metricas.html", "templates/tendencias.html", "templates/publicidad.html", "templates/_dia_reputacion.html"):
        assert "rgba(139, 92, 246" not in open(os.path.join(RAIZ, rel), encoding="utf-8").read(), rel

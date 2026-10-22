"""
Ola 3: el Dashboard (y cada pantalla) pide menos al abrirse. Medido en el navegador contra la cuenta real: el Dashboard hacía 14 pedidos al abrir (el ticker DOS veces, y dos pedidos que
solo le sirven a Stock en TODAS las pantallas); ahora hace 9, y lo que está abajo (top de modelos, últimas ventas) se pide recién cuando se acerca a la vista.
Cada pedido es una conexión del pooler de la base (15 para todo el proyecto): menos pedidos por visita es más lugar para más cuentas.
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


def test_las_pantallas_no_piden_lo_que_solo_le_sirve_a_otra():
    """/api/cobertura_variantes marca modelos de Stock masivo y /api/oportunidades_seo llena un panel de Stock: en las demás pantallas esos dos pedidos eran en vano."""
    js = _leer("static", "js", "global.js")
    variantes = js[js.index("async function marcarVariantesClaveAgotadas()"):][:500]
    assert variantes.index("[data-modelo-titulo]") < variantes.index("fetch('/api/cobertura_variantes')")
    seo = js[js.index("async function cargarOportunidadesSeo()"):][:500]
    assert seo.index("panel-oportunidades-seo") < seo.index("fetch('/api/oportunidades_seo')")
    # y las pantallas que SÍ los usan tienen lo que se busca en su HTML (no armado después por JavaScript)
    assert "data-modelo-titulo=" in _leer("templates", "stock_masivo.html") and 'id="panel-oportunidades-seo"' in _leer("templates", "index.html")


def test_el_ticker_se_pide_una_sola_vez_aunque_lo_necesiten_la_barra_y_el_dashboard():
    js = _leer("static", "js", "global.js")
    assert js.count("fetch('/api/ticker')") == 1                                         # un solo lugar lo pide
    assert "const data = await pedirTicker();" in js
    assert "pedirTicker" in _leer("templates", "dashboard_personalizable.html")


@CON_NODE
def test_pedirTicker_comparte_el_pedido_no_guarda_los_fallos_y_vuelve_a_pedir_pasados_10_segundos(tmp_path):
    js = _leer("static", "js", "global.js")
    fn = re.search(r"let _tickerPedido = null, _tickerPedidoEn = 0;\nfunction pedirTicker\(\) \{.*?\n\}\n", js.replace("\r\n", "\n"), re.S).group(0)
    guion = tmp_path / "ticker.js"
    guion.write_text(fn + """
let reloj = 1000000, llamadas = 0, fallar = false;
Date.now = () => reloj;
global.fetch = () => { llamadas++; return fallar ? Promise.resolve({ ok: false, status: 502, json: async () => null }) : Promise.resolve({ ok: true, json: async () => ({ n: llamadas }) }); };
(async () => {
  const [a, b] = await Promise.all([pedirTicker(), pedirTicker()]);          // la barra y el Dashboard a la vez
  const compartido = llamadas === 1 && a === b;
  reloj += 9000; await pedirTicker(); const antes = llamadas;                  // 9 s después: se reutiliza
  reloj += 2000; await pedirTicker(); const despues = llamadas;                // 11 s después: se vuelve a pedir
  reloj += 20000; fallar = true;
  let fallo = false; try { await pedirTicker(); } catch (e) { fallo = true; }
  fallar = false; const total = llamadas; await pedirTicker();                 // un pedido que falló NO queda guardado: el siguiente reintenta enseguida
  console.log(JSON.stringify({ compartido, antes, despues, fallo, reintento: llamadas === total + 1 }));
})();
""", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:500]
    assert json.loads(r.stdout) == {"compartido": True, "antes": 1, "despues": 2, "fallo": True, "reintento": True}


def test_lo_que_esta_abajo_del_dashboard_se_pide_cuando_se_acerca_a_la_vista():
    html = _leer("templates", "dashboard_personalizable.html")
    assert "function cuandoSeVea(elemento, cargar)" in html and "new IntersectionObserver" in html and "rootMargin: '400px 0px'" in html
    assert "cuandoSeVea(w, () => fetch('/api/dashboard/top_productos')" in html and "cuandoSeVea(w, () => fetch('/api/dashboard/ultimas_ventas')" in html
    assert "if (!('IntersectionObserver' in window)) { cargar(); return; }" in html                  # un navegador viejo sigue funcionando: pide todo como antes
    # lo de arriba de todo NO espera: la ganancia, qué hacer y los números se piden al abrir
    for pedido in ("cargarGananciaDiaVsPromedio();", "cargarAcciones();", "cargarKpisDia();", "cargarVentasHoy();"):
        assert pedido in html[html.index("document.addEventListener('DOMContentLoaded', () => {\n        const fecha"):]


def test_la_cobertura_de_costos_se_pide_junto_con_las_acciones_y_no_despues():
    html = _leer("templates", "dashboard_personalizable.html")
    asincrona = html[html.index("async function cargarAcciones()"):][:1400]
    assert "const [d, ganancia, cob] = await Promise.all([" in asincrona and "/api/dashboard/cobertura_costos" in asincrona
    assert asincrona.count("/api/dashboard/cobertura_costos") == 1                                    # ya no hay un segundo pedido que espera al primero

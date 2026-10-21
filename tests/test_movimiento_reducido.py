"""
Movimiento reducido: el CSS ya apaga todas las animaciones cuando el sistema lo pide (style.css), pero lo que se mueve desde JavaScript lo ignoraba: el conteo de números del Dashboard
(`animarNumeroHasta`, 650 ms) y cinco `scrollIntoView({ behavior: 'smooth' })`. Ahora todo mira `UX.prefiereMenosMovimiento()`. La lógica corre de verdad con node.
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
global.window = { addEventListener() {}, MutationObserver: undefined };
global.document = { addEventListener() {}, querySelectorAll() { return []; }, documentElement: {}, body: {}, activeElement: null, contains() { return true; } };
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
const fs = require('fs');
"""


def _node(codigo, tmp_path):
    ux = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "prueba.js"
    guion.write_text(PRELUDIO + f"eval(fs.readFileSync({json.dumps(ux)}, 'utf8') + '\\n;global.UX = UX;');\n{codigo}", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_el_helper_lee_la_preferencia_del_sistema(tmp_path):
    r = _node("""
      const res = {};
      window.matchMedia = (q) => ({ matches: q.includes('prefers-reduced-motion') });
      res.reducido = [UX.prefiereMenosMovimiento(), UX.comportamientoDeScroll()];
      window.matchMedia = () => ({ matches: false });
      res.normal = [UX.prefiereMenosMovimiento(), UX.comportamientoDeScroll()];
      delete window.matchMedia;                                  // un navegador sin matchMedia: se mueve como siempre y no rompe
      res.sin = [UX.prefiereMenosMovimiento(), UX.comportamientoDeScroll()];
      console.log(JSON.stringify(res));
    """, tmp_path)
    assert r == {"reducido": [True, "auto"], "normal": [False, "smooth"], "sin": [False, "smooth"]}


@CON_NODE
def test_el_conteo_de_numeros_va_directo_al_final_con_movimiento_reducido(tmp_path):
    fuente = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    funcion = fuente[fuente.index("function animarNumeroHasta"):fuente.index("// ---------- Búsqueda flexible multi-token")]
    ruta = tmp_path / "funcion.js"
    ruta.write_text(funcion, encoding="utf-8")
    r = _node(f"""
      eval(fs.readFileSync({json.dumps(str(ruta).replace(chr(92), '/'))}, 'utf8') + '\\n;global.animarNumeroHasta = animarNumeroHasta;');
      const cuadros = [];
      global.performance = {{ now: () => 0 }};
      global.requestAnimationFrame = (f) => cuadros.push(f);
      const el = {{ textContent: '' }}, fmt = (n) => 'N' + Math.round(n);
      window.matchMedia = () => ({{ matches: true }});
      animarNumeroHasta(el, 1000, fmt);
      const reducido = [el.textContent, cuadros.length];        // el número final de una vez y ningún cuadro de animación pedido
      window.matchMedia = () => ({{ matches: false }});
      el.textContent = '';
      animarNumeroHasta(el, 1000, fmt);
      console.log(JSON.stringify({{ reducido, normal: cuadros.length }}));
    """, tmp_path)
    assert r["reducido"] == ["N1000", 0] and r["normal"] == 1


def test_ningun_desplazamiento_suave_ignora_la_preferencia():
    """Todo `scrollIntoView` con animación pasa por UX.comportamientoDeScroll(): un `behavior: 'smooth'` suelto vuelve a ignorarla (la landing tiene su propio manejo)."""
    sueltos = []
    for carpeta, extension in (("static/js", ".js"), ("templates", ".html")):
        for nombre in sorted(os.listdir(os.path.join(RAIZ, carpeta))):
            if not nombre.endswith(extension) or nombre == "landing.html":
                continue
            texto = open(os.path.join(RAIZ, carpeta, nombre), encoding="utf-8").read()
            if re.search(r"behavior:\s*['\"]smooth['\"]", texto):
                sueltos.append(f"{carpeta}/{nombre}")
    assert not sueltos, sueltos

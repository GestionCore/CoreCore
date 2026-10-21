"""
Diálogo de confirmación (base.html): el botón era SIEMPRE rojo («btn-danger»), también al guardar 12 costos o cambiar un precio, y el rojo dejaba de significar peligro. Ahora es violeta (acción) y rojo solo cuando
la persona está por destruir algo que no se deshace (`peligro = true`). La lógica del diálogo corre de verdad con node; que cada acción destructiva pida el rojo se revisa en las plantillas.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _script_del_dialogo():
    html = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    fin = html.index("window.confirmarDecision = function")
    inicio = html.rindex("<script", 0, fin)
    cuerpo = html[html.index(">", inicio) + 1:html.index("</script>", fin)]
    return cuerpo


PRELUDIO = r"""
const elementos = {};
function el(id) { return elementos[id] = elementos[id] || { id, style: {}, textContent: '', className: '', focus() {}, addEventListener() {} }; }
global.document = { getElementById: el, addEventListener() {}, activeElement: null, contains() { return true; }, body: {} };
global.window = global; global._ciclarFocoEn = () => {};
"""


@CON_NODE
def test_el_boton_es_violeta_salvo_que_se_pida_peligro(tmp_path):
    ruta = tmp_path / "dialogo.js"
    ruta.write_text(PRELUDIO + _script_del_dialogo() + r"""
    const ok = el('modal-confirmar-ok'), res = {};
    el('modal-confirmar').style.display = 'none';
    confirmarAccion('¿Guardar?', null, 'Guardar costos', 'detalle');                  res.neutro = [ok.className, ok.textContent];
    cerrarModalConfirmar();
    confirmarAccion('¿Borrar?', null, 'Borrar', 'detalle', true);                    res.peligro = [ok.className, ok.textContent];
    cerrarModalConfirmar();
    confirmarAccion('¿Otra vez neutro?', null, 'Aplicar');                             res.volvio = ok.className;       // el rojo no se queda pegado de la vez anterior
    cerrarModalConfirmar();
    confirmarDecision('¿Quitar?', 'Quitar', '', true);                                 res.decision_peligro = ok.className;
    cerrarModalConfirmar();
    confirmarDecision('¿Cambiar precios?', 'Cambiar precios', 'sub');                  res.decision_neutra = ok.className;
    console.log(JSON.stringify(res));
    """, encoding="utf-8")
    r = subprocess.run(["node", str(ruta)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    res = json.loads(r.stdout)
    assert res == {"neutro": ["btn btn-primary", "Guardar costos"], "peligro": ["btn btn-danger", "Borrar"], "volvio": "btn btn-primary",
                   "decision_peligro": "btn btn-danger", "decision_neutra": "btn btn-primary"}


def test_el_boton_de_la_plantilla_arranca_violeta():
    html = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    assert 'class="btn btn-primary" id="modal-confirmar-ok"' in html


# Lo que destruye algo que no se deshace pide el rojo; el resto, no.
DESTRUCTIVAS = [
    ("competencia.html", '"Dejar de seguir", "", true]'),
    ("costos.html", '"Eliminar", "", true]'),
    ("promociones.html", '"Quitar descuento", "", true]'),
    ("ventas_manuales.html", 'se devuelve automáticamente.", true]'),
    ("_dia_preguntas.html", "no se toca nada en Mercado Libre.', true)"),
    ("admin_panel.html", "esActivo ? 'Desactivar' : 'Activar', '', esActivo)"),
]


@pytest.mark.parametrize("plantilla, fragmento", DESTRUCTIVAS)
def test_cada_accion_que_destruye_algo_pide_el_boton_rojo(plantilla, fragmento):
    assert fragmento in open(os.path.join(RAIZ, "templates", plantilla), encoding="utf-8").read()


def test_ninguna_confirmacion_de_guardar_o_cambiar_pide_rojo():
    """Guardar costos, cambiar precios, aplicar stock, crear un descuento o registrar una venta no destruyen nada: nunca llevan `true` de peligro."""
    for plantilla, patron in (("costos.html", r"confirmarDecision\(pregunta, 'Guardar costos', detalle\)"), ("precios.html", r"'Cambiar precios',"),
                              ("stock_masivo.html", r"'Aplicar ca"), ("promociones.html", r"'Crear descuento'"), ("ventas_manuales.html", r"'Registrar y descontar'")):
        texto = open(os.path.join(RAIZ, "templates", plantilla), encoding="utf-8").read()
        coincidencia = re.search(patron, texto)
        assert coincidencia, (plantilla, patron)
        resto = texto[coincidencia.end():coincidencia.end() + 400].split(";")[0]
        assert not re.search(r",\s*true\s*\)", resto), (plantilla, resto[:120])

"""
Jerarquía de botones (PLAN_UX_200.md, ítems 34, 91, 99 y 119): violeta = principal (uno por pantalla o por lista), gris = secundario, rojo = destructivo.
Naranja y verde son ESTADOS, no botones: antes cada fila de «Lo que tenés que hacer», de Calidad, de Opiniones, de Promociones y del Embudo llevaba su botón naranja o rojo
(cinco «Ver cuáles» iguales y de color), sin criterio de cuál era el que más valía. Ahora solo el primero de cada lista es violeta y la urgencia se ve en la tarjeta.
"""
import glob
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


def test_no_existen_botones_de_color_por_estado():
    """btn-urgente (rojo) y btn-alerta (naranja) ya no se usan en ninguna plantilla, script ni estilo: un estado se muestra con la tarjeta, la pastilla o el borde, no con el botón."""
    usados = []
    for ruta in glob.glob(os.path.join(RAIZ, "templates", "*.html")) + glob.glob(os.path.join(RAIZ, "static", "js", "*.js")) + glob.glob(os.path.join(RAIZ, "static", "css", "*.css")) + glob.glob(os.path.join(RAIZ, "*.py")):
        if re.search(r"btn-urgente|btn-alerta", open(ruta, encoding="utf-8").read()):
            usados.append(os.path.relpath(ruta, RAIZ))
    assert not usados, f"Usan botones de color por estado (usá btn-primary / btn-secondary / btn-danger): {usados}"


def test_las_listas_de_filas_solo_ponen_el_boton_principal_en_la_primera():
    for plantilla, texto in (("calidad.html", "Ver cuáles"), ("opiniones.html", "Ver opiniones"), ("promociones.html", "Promocionar"), ("embudo_conversion.html", "Revisar ficha"),
                             ("index.html", "Gestionar"), ("_dia_pendientes.html", "m.link_texto")):
        fuente = _leer("templates", plantilla)
        linea = next(l for l in fuente.splitlines() if texto in l and "btn" in l)
        assert "'btn-primary' if loop.first" in linea and "'btn-secondary'" in linea, (plantilla, linea.strip()[:160])


def test_el_boton_de_un_aviso_es_principal_salvo_donde_la_pantalla_ya_tiene_su_principal():
    """Ganancia Real tiene su principal en la descarga del PDF y Stock en «Gestionar» de lo que hay que reponer: sus avisos solo llevan hacia ahí (secundarios)."""
    assert 'cta_clase="btn-primary"' in _leer("templates", "_ux.html")                                  # por defecto
    esperado = {"costos.html": "btn-primary", "_dia_reputacion.html": "btn-primary", "metricas.html": "btn-secondary", "index.html": "btn-secondary"}
    for plantilla, clase in esperado.items():
        usados = [m.group(1) for m in re.finditer(r'banner\(.*?"(btn-[a-z]+)"\s*\)\s*\}\}', _leer("templates", plantilla))]
        assert usados and set(usados) == {clase}, (plantilla, usados)


def test_cancelar_la_suscripcion_es_un_boton_destructivo_rojo():
    assert 'class="btn btn-danger" id="btn-confirmar-cancelar"' in _leer("templates", "suscripcion.html")


def _accion(argumentos, tmp_path):
    ruta = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "accion.js"
    guion.write_text("""
const fs = require('fs'), vm = require('vm');
const caja = { console, document: { addEventListener() {}, querySelectorAll: () => [] } };
caja.window = caja; caja.addEventListener = () => {};
vm.createContext(caja);
vm.runInContext(fs.readFileSync(%s, 'utf8') + ';this.UX = UX;', caja);
console.log(JSON.stringify(caja.UX.accion(%s)));
""" % (json.dumps(ruta), json.dumps(argumentos)), encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


@CON_NODE
def test_la_cola_de_acciones_solo_pinta_de_violeta_la_principal_y_la_urgencia_va_en_la_tarjeta(tmp_path):
    base = {"categoria": "stock", "titulo": "Reponer", "detalle": "x", "link": "/stock", "linkTexto": "Ir"}
    principal = _accion({**base, "prioridad": "urgente", "principal": True}, tmp_path)
    otra_urgente = _accion({**base, "prioridad": "urgente"}, tmp_path)
    opcional = _accion({**base, "prioridad": "opcional", "principal": True}, tmp_path)
    assert 'class="btn btn-primary"' in principal and 'class="btn btn-secondary"' in otra_urgente and 'class="btn btn-primary"' in opcional
    assert "ux-item-accion ux-danger" in otra_urgente                                                  # sigue siendo roja: la urgencia está en la tarjeta
    assert "btn-urgente" not in otra_urgente and "btn-alerta" not in otra_urgente


def test_el_dashboard_marca_como_principal_solo_la_primera_accion():
    html = _leer("templates", "dashboard_personalizable.html")
    assert "d.acciones.map((a, i) => UX.accion({" in html and "principal: i === 0 }))" in html

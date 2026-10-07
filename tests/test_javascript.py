"""
El JavaScript no tiene un compilador que avise: una función borrada que sigue siendo llamada rompe la pantalla recién cuando alguien la abre. Pasó
al quitar el botón de resumen rápido: quedó una llamada a cargarHud() en el arranque, y cada pantalla dejó de iniciar el tutorial, los avisos y
la actualización del ticker. Estas pruebas buscan esa clase de error sin abrir un navegador.
"""
import glob
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVOS_JS = sorted(glob.glob(os.path.join(RAIZ, "static", "js", "*.js")))
PLANTILLAS = sorted(glob.glob(os.path.join(RAIZ, "templates", "*.html")))


def _leer(ruta):
    return open(ruta, encoding="utf-8").read()


FUENTE = "\n".join(_leer(r) for r in ARCHIVOS_JS + PLANTILLAS)
DEFINIDOS = (
    set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", FUENTE)) | set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", FUENTE))
    | set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", FUENTE)) | set(re.findall(r"\b(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", FUENTE))
)
DEL_NAVEGADOR = {"if", "for", "while", "switch", "return", "function", "event", "this", "document", "window", "alert", "confirm", "history", "location", "localStorage",
                 "navigator", "Math", "JSON", "Number", "String", "Array", "Object", "Date", "Promise", "console", "setTimeout", "setInterval", "fetch", "parseInt", "parseFloat",
                 "encodeURIComponent", "requestAnimationFrame", "Chart", "mostrarToast"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
@pytest.mark.parametrize("ruta", ARCHIVOS_JS, ids=os.path.basename)
def test_el_javascript_no_tiene_errores_de_sintaxis(ruta):
    r = subprocess.run(["node", "--check", ruta], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:500]


def test_el_arranque_global_solo_llama_funciones_que_existen():
    js = _leer(os.path.join(RAIZ, "static", "js", "global.js"))
    inicio = js.index("document.addEventListener('DOMContentLoaded', () => {", js.index("// ---------- Arranque global"))
    arranque = js[inicio:]
    sin_comentarios = re.sub(r"//[^\n]*", "", arranque)
    llamadas = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\(", sin_comentarios)) - DEL_NAVEGADOR
    faltan = sorted(n for n in llamadas if n not in DEFINIDOS)
    assert not faltan, f"El arranque llama a funciones que no existen en ningún lado: {faltan}"


def test_los_botones_de_las_plantillas_llaman_funciones_que_existen():
    faltan = {}
    for ruta in PLANTILLAS:
        for evento, nombre in re.findall(r'\bon(click|change|input|submit|keydown)="\s*(?:return\s+|if\s*\([^)]*\)\s*)?([A-Za-z_$][\w$.]*)\(', _leer(ruta)):
            base = nombre.split(".")[0]
            if base in DEL_NAVEGADOR or base in DEFINIDOS:
                continue
            faltan.setdefault(base, set()).add(os.path.basename(ruta))
    assert not faltan, {k: sorted(v) for k, v in faltan.items()}


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_la_busqueda_no_distingue_mayusculas_ni_acentos():
    """"pantalon" tiene que encontrar "Pantalón": en Stock, Stock masivo y donde se use coincideBusqueda casi nadie tipea las tildes."""
    js = _leer(os.path.join(RAIZ, "static", "js", "global.js"))
    inicio = js.index("function _sinAcentos")
    fin = js.index("// ---------- IDs copiables")
    guion = (
        js[inicio:fin]
        + "\nconst casos = ["
        + "['Pantalón Cargo Hombre', 'pantalon', true], ['Pantalón Cargo Hombre', 'PANTALÓN cargo', true], ['Camiseta Niño', 'nino', true],"
        + "['Pantalón Cargo Hombre', 'pantalon jean', false], ['Remera', '', true], ['Remera', '   ', true]];"
        + "\nconst mal = casos.filter(([texto, q, esperado]) => coincideBusqueda(texto, q) !== esperado);"
        + "\nif (mal.length) { console.error(JSON.stringify(mal)); process.exit(1); }"
    )
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:500]

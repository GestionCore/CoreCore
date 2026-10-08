r"""
XSS en el navegador: todo texto que puede venir de un tercero (el comprador que escribe una pregunta o una opinión, el vendedor rival de Tendencias, el título de una publicación) y se
arma dentro de HTML con una plantilla de JavaScript (`innerHTML = \`…${x}…\``) tiene que pasar por UX.esc / escapeHtml. Esta prueba recorre las plantillas y los .js, mira cada ${…} que
mencione un campo de texto y falla si no está escapado. Las excepciones verificadas a mano (constantes, números, HTML ya armado y escapado) están en PERMITIDAS con su motivo.
Hallazgo real que motivó esto (2026-10-08): el cajón de cada publicación mostraba sin escapar las preguntas y opiniones de compradores, las descripciones y los títulos del buscador.
"""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPOS = re.compile(r"\b(titulo|title|nickname|texto|descripcion|comentario|contenido|respuesta|pregunta|termino|motivo|mensaje|error|nombre|name|marca|razon|comprador|buyer|detalle|valor|vendedor)\b", re.I)
ESCAPA = re.compile(r"esc\(|escapeHtml\(|encodeURIComponent\(|Number\(|\.toFixed\(|\.length\b")
TEXTO_FIJO = re.compile(r"""^[^?]+\?\s*(['"][^'"$`]*['"])\s*:\s*(['"][^'"$`]*['"])$""")

# (archivo, expresión) -> por qué es seguro. Solo lo verificado a mano.
PERMITIDAS = {
    (os.path.join("templates", "calculadora.html"), "titulo"): "texto fijo elegido por el código ('Te queda…' / 'Tu ganancia neta real')",
    (os.path.join("templates", "metricas.html"), "titulo"): "tooltip del mapa de calor: día + hora + unidades, todo número o constante",
    (os.path.join("templates", "costos.html"), "texto"): "frase armada con plata() y porcentajes, sin texto externo",
    (os.path.join("templates", "dashboard_personalizable.html"), "w.nombre"): "nombres fijos de los widgets (lista en el propio archivo)",
    (os.path.join("templates", "dashboard_personalizable.html"), "salida.texto"): "texto fijo de la salida del hero ('Cargar los costos'…)",
    (os.path.join("static", "js", "global.js"), "titulo"): "frase del chat de costos armada con cantidades",
    (os.path.join("templates", "tendencias.html"), "nombre"): "ya viene armado y escapado por _renderVendedor (esc + urlSegura)",
}


def _expresiones(literal):
    out, i = [], 0
    while True:
        i = literal.find("${", i)
        if i < 0:
            return out
        prof, j = 1, i + 2
        while j < len(literal) and prof:
            prof += (literal[j] == "{") - (literal[j] == "}")
            j += 1
        out.append(" ".join(literal[i + 2:j - 1].split()))
        i = j


def _literales(src):
    """Los textos entre backticks (con ${…} anidados) de un archivo."""
    pos = 0
    while True:
        a = src.find("`", pos)
        if a < 0:
            return
        j, prof = a + 1, 0
        while j < len(src):
            c = src[j]
            if c == "\\":
                j += 2
                continue
            if c == "$" and src[j + 1:j + 2] == "{":
                prof += 1
                j += 2
                continue
            if prof and c == "}":
                prof -= 1
            elif not prof and c == "`":
                break
            j += 1
        yield src[a + 1:j]
        pos = j + 1


def _sin_escapar():
    encontrados = set()
    for ruta in glob.glob(os.path.join(RAIZ, "templates", "*.html")) + glob.glob(os.path.join(RAIZ, "static", "js", "*.js")):
        rel = os.path.relpath(ruta, RAIZ)
        for literal in _literales(open(ruta, encoding="utf-8").read()):
            if "<" not in literal or "${" not in literal:
                continue
            for e in _expresiones(literal):
                sin_cadenas = re.sub(r"""('[^']*'|"[^"]*")""", "", e)          # una palabra dentro de un texto fijo («sin comentarios de texto») no es un campo
                if "`" in e or not CAMPOS.search(sin_cadenas) or ESCAPA.search(e) or TEXTO_FIJO.match(e):
                    continue                           # un literal anidado se revisa por su cuenta; lo escapado o fijo no es riesgo
                if re.fullmatch(r"\w*(Html|html)\w*|color|tono|clase|estilo|icono", e):
                    continue                           # HTML que otro código ya armó (se revisa donde se arma)
                encontrados.add((rel, e))
    return encontrados


def test_ningun_texto_de_terceros_entra_a_un_innerhtml_sin_escapar():
    nuevos = sorted(_sin_escapar() - set(PERMITIDAS))
    assert not nuevos, (
        "Posible XSS: estos ${…} arman HTML con un campo de texto sin UX.esc(): "
        + "; ".join(f"{a}: ${{{e}}}" for a, e in nuevos)
        + ". Escapalo con UX.esc(...) (o, si es una constante verificada, agregalo a PERMITIDAS con su motivo)."
    )


def test_el_cajon_de_publicacion_escapa_preguntas_opiniones_y_descripcion():
    """Los tres textos que escribe un tercero o el propio vendedor y que el cajón mostraba crudos (regresión puntual)."""
    src = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    for crudo in ("${p.texto}", "${p.respuesta}", "${d.descripcion || ''}", "${item.texto}", "${o.termino}", "${r.contenido || ''}"):
        assert crudo not in src, f"{crudo} se inserta sin escapar en global.js"


def test_no_quedan_entradas_viejas_en_las_excepciones():
    sobrantes = sorted(set(PERMITIDAS) - _sin_escapar())
    assert not sobrantes, f"Ya no hacen falta (sacalas de PERMITIDAS): {sobrantes}"

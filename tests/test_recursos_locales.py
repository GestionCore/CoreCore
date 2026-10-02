"""CoreLux sirve sus fuentes y sus librerías desde /static: ninguna página depende de un servidor de terceros (más rápido, funciona aunque ese servidor caiga, y no le
manda a nadie la IP de la persona). Si hace falta una librería nueva, se descarga a static/js/vendor/ con su versión."""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTERNOS = re.compile(r"""(?:src|href)=["']https?://(?!(?:www\.)?(?:corelux\.app|mercadolibre|mercadopago|api\.whatsapp|wa\.me)\b)[^"']+""")


def test_ninguna_plantilla_carga_scripts_ni_estilos_de_terceros():
    pedidos = {}
    for ruta in glob.glob(os.path.join(RAIZ, "templates", "*.html")):
        for m in EXTERNOS.findall(open(ruta, encoding="utf-8").read()):
            if re.search(r"<(?:script|link)[^>]*" + re.escape(m), open(ruta, encoding="utf-8").read()):
                pedidos.setdefault(os.path.basename(ruta), []).append(m)
    assert not pedidos, f"Plantillas que cargan recursos externos: {pedidos}"


def test_las_fuentes_y_librerias_que_se_piden_existen():
    css = open(os.path.join(RAIZ, "static", "css", "fonts.css"), encoding="utf-8").read()
    for archivo in re.findall(r"url\('/static/(fonts/[\w.-]+\.woff2)(?:\?v=\d+)?'\)", css):
        assert os.path.exists(os.path.join(RAIZ, "static", archivo)), archivo
    assert os.path.getsize(os.path.join(RAIZ, "static", "js", "vendor", "chart.umd.min.js")) > 150_000


def test_las_fuentes_van_con_version_para_que_el_servidor_las_cachee_un_anio():
    css = open(os.path.join(RAIZ, "static", "css", "fonts.css"), encoding="utf-8").read()
    urls = re.findall(r"url\('([^']+)'\)", css)
    assert urls and all("?v=" in u for u in urls)          # seguridad.py solo da caché larga a /static con ?v=

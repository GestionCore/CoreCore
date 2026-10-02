import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_la_imagen_no_lleva_datos_de_usuarios_ni_secretos():
    """El Dockerfile copia la carpeta entera: lo que no esté en .dockerignore termina en la imagen que se sube a Fly. Pasó con respaldos/ (un zip
    con los datos de todos los usuarios) y con static/_prev (vistas previas con números reales, que además se habrían servido por la web)."""
    lineas = {l.strip() for l in open(os.path.join(RAIZ, ".dockerignore"), encoding="utf-8") if l.strip() and not l.startswith("#")}
    for obligatorio in (".env", "respaldos/", "*.zip", "static/_prev/", ".claude/", "venv/"):
        assert obligatorio in lineas, f"falta {obligatorio} en .dockerignore"

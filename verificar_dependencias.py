"""
Se corre al CONSTRUIR la imagen de Docker (ver Dockerfile): si falta cualquier dependencia, la construcción falla y el deploy se corta ANTES de tocar las máquinas
de producción. Existe por un problema real (2026-10-06): gunicorn 26 carga `packaging` en su worker gevent sin declararlo como dependencia; al sacar Celery (que
lo traía de rebote) la imagen nueva arrancaba y se caía, y las dos máquinas quedaron apagadas. En la PC de desarrollo la librería sí estaba, por eso nada lo avisó.

Qué comprueba:
  1. que el worker con el que corre producción (gunicorn + gevent) se pueda cargar de verdad;
  2. que todo módulo de terceros que importa el código de CoreLux esté instalado (se lee el código con `ast`; no se importa nada de la app).
"""
import ast
import importlib.util
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
IGNORAR = {"venv", ".venv", "tests", "docs", "deploy", "node_modules", "static", "migrations", "__pycache__", ".git", ".claude", "schema", "respaldos"}
# nombres que se importan solo dentro de un try/except o en Windows/desarrollo: no son requisito de producción
OPCIONALES = {"waitress", "pyautogui", "celery", "kombu", "billiard"}


def _locales():
    nombres = {os.path.splitext(f)[0] for f in os.listdir(RAIZ) if f.endswith(".py")}
    nombres |= {d for d in os.listdir(RAIZ) if os.path.isdir(os.path.join(RAIZ, d)) and os.path.exists(os.path.join(RAIZ, d, "__init__.py"))}
    return nombres


def importados_de_terceros():
    locales, stdlib = _locales(), set(sys.stdlib_module_names)
    usados = {}
    for carpeta, dirs, archivos in os.walk(RAIZ):
        dirs[:] = [d for d in dirs if d not in IGNORAR]
        for archivo in archivos:
            if not archivo.endswith(".py"):
                continue
            ruta = os.path.join(carpeta, archivo)
            try:
                arbol = ast.parse(open(ruta, encoding="utf-8").read())
            except SyntaxError as e:
                print(f"No se pudo leer {ruta}: {e}")
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    nombres = [a.name.split(".")[0] for a in nodo.names]
                elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                    nombres = [nodo.module.split(".")[0]]
                else:
                    continue
                for n in nombres:
                    if n not in stdlib and n not in locales and n not in OPCIONALES:
                        usados.setdefault(n, os.path.relpath(ruta, RAIZ))
    return usados


def comprobar(importar=importlib.import_module, hay_modulo=lambda n: importlib.util.find_spec(n) is not None, comprobar_worker=None):
    """Devuelve la lista de problemas (vacía = todo bien). `importar` y `hay_modulo` se pueden reemplazar en las pruebas."""
    problemas = []
    if comprobar_worker is None:
        comprobar_worker = os.name != "nt"          # gunicorn no corre en Windows: el worker se comprueba en la imagen Linux
    if comprobar_worker:
        try:
            importar("gunicorn.workers.ggevent")   # el worker con el que corre producción
            importar("gevent")
        except Exception as e:
            problemas.append(f"el worker de producción (gunicorn + gevent) no carga: {type(e).__name__}: {e}")
    for nombre, archivo in sorted(importados_de_terceros().items()):
        if not hay_modulo(nombre):
            problemas.append(f"falta «{nombre}» (lo importa {archivo}): agregarlo a requirements.txt")
    return problemas


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    problemas = comprobar()
    if problemas:
        print("❌ Dependencias incompletas:")
        for problema in problemas:
            print("  - " + problema)
        sys.exit(1)
    extra = "" if os.name == "nt" else " y el worker de producción"
    print(f"✅ Dependencias completas ({len(importados_de_terceros())} módulos de terceros{extra}).")


if __name__ == "__main__":
    main()

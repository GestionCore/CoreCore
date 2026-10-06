"""
Lo que hace falta para que producción ARRANQUE. Pasó (2026-10-06): gunicorn 26 importa `packaging` en su worker gevent sin declararlo; al sacar Celery (que lo traía de
rebote) la imagen se construía bien, arrancaba y se caía, y las dos máquinas de Fly quedaron apagadas. En la PC de desarrollo la librería estaba, así que nada falló.
"""
import ast
import importlib.util
import os
import re

import verificar_dependencias as v

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _requeridos():
    nombres = set()
    for linea in open(os.path.join(RAIZ, "requirements.txt"), encoding="utf-8"):
        linea = linea.split("#")[0].strip()
        if linea:
            nombres.add(re.split(r"[\[<>=!~ ;]", linea)[0].lower().replace("_", "-"))
    return nombres


def test_todo_lo_que_importa_el_worker_de_produccion_esta_declarado():
    """Se lee el código del worker gevent de gunicorn INSTALADO: cada librería de terceros que importa tiene que estar en requirements.txt."""
    spec = importlib.util.find_spec("gunicorn")
    ruta = os.path.join(os.path.dirname(spec.origin), "workers", "ggevent.py")
    stdlib = set(__import__("sys").stdlib_module_names)
    importados = set()
    for nodo in ast.walk(ast.parse(open(ruta, encoding="utf-8").read())):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            importados.add(nodo.module.split(".")[0])
    de_terceros = {n for n in importados if n not in stdlib and n != "gunicorn"}
    faltan = sorted(n for n in de_terceros if n.lower().replace("_", "-") not in _requeridos())
    assert not faltan, f"El worker gevent de gunicorn importa {faltan}, que no está en requirements.txt: la imagen arranca y se cae."


def test_packaging_esta_declarado():
    assert "packaging" in _requeridos()


def test_la_imagen_se_niega_a_construirse_si_falta_una_dependencia():
    dockerfile = open(os.path.join(RAIZ, "Dockerfile"), encoding="utf-8").read()
    copiar = dockerfile.index("COPY . .")
    assert "RUN python verificar_dependencias.py" in dockerfile[copiar:]        # después de copiar el código: lee los import de todos los módulos


def test_el_verificador_detecta_que_el_worker_no_carga():
    def importar(nombre):
        if nombre == "gunicorn.workers.ggevent":
            raise ModuleNotFoundError("No module named 'packaging'")

    problemas = v.comprobar(importar=importar, hay_modulo=lambda n: True, comprobar_worker=True)
    assert len(problemas) == 1 and "packaging" in problemas[0] and "gunicorn + gevent" in problemas[0]


def test_el_verificador_detecta_un_modulo_de_terceros_que_no_esta_instalado():
    problemas = v.comprobar(importar=lambda n: None, hay_modulo=lambda n: n != "flask", comprobar_worker=False)
    assert any("«flask»" in p and "requirements.txt" in p for p in problemas)


def test_el_verificador_da_verde_si_todo_esta():
    assert v.comprobar(importar=lambda n: None, hay_modulo=lambda n: True, comprobar_worker=True) == []

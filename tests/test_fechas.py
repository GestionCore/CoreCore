"""
El servidor corre en UTC: pasadas las 21 h argentinas, datetime.now()/date.today() ya dan "mañana". Todo lo que decide "hoy" de un negocio argentino
tiene que usar utils.hoy_argentina() o datetime.now(ARGENTINA). Esta prueba falla si vuelve a aparecer una fecha "a secas" en el código de la app.
"""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROHIBIDO = re.compile(r"datetime\.now\(\)(?!\.timestamp|\.astimezone)|\bdate\.today\(\)|datetime\.today\(\)")
PERMITIDOS = {"respaldo.py"}          # nombres de archivo de los respaldos: la hora local de quien lo corre


def _archivos():
    for patron in ("*.py", "auth/*.py", "tasks/*.py"):
        for ruta in glob.glob(os.path.join(RAIZ, patron)):
            if os.path.basename(ruta) not in PERMITIDOS:
                yield ruta


def test_no_hay_fechas_del_servidor_para_decidir_hoy():
    encontrados = []
    for ruta in _archivos():
        for n, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if linea.strip().startswith("#"):
                continue
            if PROHIBIDO.search(linea):
                encontrados.append(f"{os.path.relpath(ruta, RAIZ)}:{n}: {linea.strip()[:90]}")
    assert not encontrados, "Usá hoy_argentina() o datetime.now(ARGENTINA):\n" + "\n".join(encontrados)

"""
El servidor corre en UTC: pasadas las 21 h argentinas, datetime.now()/date.today() ya dan "mañana". Todo lo que decide "hoy" de un negocio argentino
tiene que usar utils.hoy_argentina() o datetime.now(ARGENTINA). Esta prueba falla si vuelve a aparecer una fecha "a secas" en el código de la app.
"""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROHIBIDO = re.compile(r"datetime\.now\(\)(?!\.timestamp|\.astimezone)|\bdate\.today\(\)|datetime\.today\(\)")
PERMITIDOS = {"respaldo.py", "enter.py"}          # respaldo.py: nombres de archivo con la hora local de quien lo corre; enter.py: script personal del dueño, no es parte de la app


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


# ── Las fechas se muestran para personas ("2 sep"), nunca como 2026-09-02 ──────────────────────────────────────────────────────────────────────
FECHA_CRUDA = re.compile(r"(?P<antes>.)\{\{\s*(?P<expr>[A-Za-z_][\w.]*?(?:fecha|fecha_inicio|fecha_fin|fecha_cambio|vigencia_desde|vigencia_hasta))\s*\}\}")
FECHAS_CRUDAS_PERMITIDAS = {                      # (plantilla, expresión): por qué no es para una persona
    ("_dia_despacho.html", "fecha"): "constante de JavaScript para comparar con el día de hoy",
    ("timeline_publicacion.html", "e.fecha"): "viene ya armada como texto del evento («hace 2 días»…)",
    ("cobros.html", "sin_fecha"): "cantidad de ventas sin fecha de acreditación: es un número, no una fecha",
}


def test_ninguna_plantilla_muestra_una_fecha_en_formato_iso():
    """`{{ x.fecha }}` a secas imprime 2026-09-02: usá `{{ x.fecha|fecha }}` («2 sep») y dejá el ISO en data-orden. Los atributos y las constantes JS (entre comillas) no cuentan."""
    crudas = []
    for ruta in glob.glob(os.path.join(RAIZ, "templates", "*.html")):
        nombre = os.path.basename(ruta)
        for m in FECHA_CRUDA.finditer(open(ruta, encoding="utf-8").read()):
            if m.group("antes") in "\"'" or (nombre, m.group("expr")) in FECHAS_CRUDAS_PERMITIDAS:
                continue
            crudas.append(f"{nombre}: {{{{ {m.group('expr')} }}}}")
    assert not crudas, "Fecha en formato ISO a la vista (usá |fecha): " + "; ".join(sorted(set(crudas)))

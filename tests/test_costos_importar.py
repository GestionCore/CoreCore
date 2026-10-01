import io
import pytest
from openpyxl import Workbook
import costos_importar as ci
from tests.conftest import CursorFalso


@pytest.mark.parametrize("crudo, esperado", [
    ("12.500,50", 12500.5), ("12500.5", 12500.5), ("$ 12.500", 12500.0), ("12.000", 12000.0), (12000, 12000.0),
    ("1.234.567", 1234567.0), ("8,5", 8.5), ("0", 0.0), ("abc", None), ("", None), (None, None), (-5, None), ("-3", None),
])
def test_parsear_monto(crudo, esperado):
    assert ci.parsear_monto(crudo) == esperado


def _xlsx(filas):
    libro = Workbook()
    for f in filas:
        libro.active.append(f)
    s = io.BytesIO()
    libro.save(s)
    return s.getvalue()


def test_lee_excel_y_csv_con_la_misma_forma():
    encabezado = ["ID de publicación", "Título (no editar)", "Costo de fabricación ($)"]
    de_excel = ci.leer_archivo("costos.xlsx", _xlsx([encabezado, ["MLA1", "Remera", 4500], ["MLA2", "Termo", None]]))
    csv_es = "ID de publicación;Título;Costo de fabricación ($)\nMLA1;Remera;4.500\nMLA2;Termo;\n".encode("utf-8")
    assert de_excel == [("MLA1", 4500), ("MLA2", None)]
    assert [(i, ci.parsear_monto(c)) for i, c in ci.leer_archivo("costos.csv", csv_es)] == [("MLA1", 4500.0), ("MLA2", None)]


def test_archivo_sin_las_columnas_da_un_error_claro():
    with pytest.raises(ValueError, match="plantilla"):
        ci.leer_archivo("x.csv", b"a;b\n1;2\n")
    with pytest.raises(ValueError, match="Excel"):
        ci.leer_archivo("x.pdf", b"")


def test_vista_previa_separa_cambios_iguales_ajenas_y_errores():
    existentes = [("MLA1", "Remera", 4000), ("MLA2", "Termo", 9000), ("MLA3", "Mate", None)]
    filas = [("MLA1", "4.500"), ("MLA2", 9000), ("MLA3", ""), ("MLA9", 100), ("MLA1", 1), ("MLA2", "mucho")]
    p = ci.armar_vista_previa(CursorFalso(existentes), 1, filas)
    assert p["cambios"] == [{"id_meli": "MLA1", "titulo": "Remera", "antes": 4000.0, "despues": 4500.0}]
    assert p["sin_cambio"] == 1                       # MLA2 con el mismo costo
    assert p["total_ignoradas"] == 1                  # MLA9 no es de esta cuenta
    assert {e["id"] for e in p["errores"]} == {"MLA1", "MLA2"}   # repetida y monto inválido (la celda vacía no se toca)


def test_aplicar_valida_otra_vez_y_filtra_por_cuenta():
    cur = CursorFalso()
    cur.rowcount = 1
    n = ci.aplicar(cur, 7, [{"id_meli": "MLA1", "despues": 4500}, {"id_meli": "MLA2", "despues": "mal"}, {"id_meli": "", "despues": 1}, {"id_meli": "MLA3", "despues": -2}])
    assert n == 1 and len(cur.consultas) == 1
    sql, params = cur.consultas[0]
    assert "cuenta_id = %s" in sql and params == (4500.0, 7, "MLA1")

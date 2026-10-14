"""
Stock agrupa las publicaciones por modelo y junta las repetidas de una MISMA variante (Clásica y Premium del mismo color) en una fila. Lo que distingue a una variante es su etiqueta
(«Azul», «128 GB / Azul»), no solo el talle: un termo de 6 colores —todos con talle «Único»— tiene que mostrar 6 variantes con su stock cada una, no una sola.
"""
import catalogo


class _Cursor:
    def __init__(self, filas):
        self.filas, self.actual = filas, []

    def execute(self, sql, params=None):
        self.actual = self.filas if "variantes_deduplicadas" in sql else []

    def fetchall(self):
        return self.actual


class _Conexion:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor(self.filas)


def _fila(id_meli, propio, full, talle, etiqueta, titulo="Termo Acero 1l"):
    return (id_meli, titulo, 10000, "active", None, None, None, None, None, propio, full, talle, etiqueta)


def _modelos(monkeypatch, filas):
    monkeypatch.setattr(catalogo.db, "conexion_usuario", lambda u, c=None: _Conexion(filas))
    return catalogo.obtener_productos_y_estadisticas(1, 1)[0]


def test_los_colores_de_una_publicacion_sin_talle_son_variantes_distintas(monkeypatch):
    (m,) = _modelos(monkeypatch, [_fila("MLA1", 3, 0, "Único", "Azul"), _fila("MLA1", 0, 2, "Único", "Rojo"), _fila("MLA1", 5, 0, "Único", "Negro")])
    assert sorted(v["variante"] for v in m["variantes"]) == ["Azul", "Negro", "Rojo"]
    assert m["stock_propio"] == 8 and m["stock_full"] == 2                                    # el stock de cada color suma, no se queda con el mayor


def test_la_misma_variante_publicada_dos_veces_sigue_siendo_una_fila(monkeypatch):
    (m,) = _modelos(monkeypatch, [_fila("MLA1", 3, 0, "M", "M / Negro"), _fila("MLA2", 5, 0, "M", "M / Negro")])
    (v,) = m["variantes"]
    assert v["propio"] == 5 and v["revisar_duplicado"] is True                                # se junta y avisa que las hermanas tienen distinto stock

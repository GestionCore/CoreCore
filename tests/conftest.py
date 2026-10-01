import os
import sys

# Las pruebas se corren desde la raíz del proyecto: los módulos (utils, precios, cobros…) viven ahí.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


class CursorFalso:
    """Cursor de mentira para probar funciones que arman datos a partir de consultas: devuelve, en orden, los resultados que se le cargan."""

    def __init__(self, *resultados):
        self.resultados = list(resultados)
        self.consultas = []
        self._actual = []

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        self._actual = self.resultados.pop(0) if self.resultados else []

    def fetchall(self):
        return self._actual

    def fetchone(self):
        return self._actual[0] if self._actual else None

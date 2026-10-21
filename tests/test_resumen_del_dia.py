"""
Resumen del día (tarjeta «Ventas hoy» del Dashboard): lo de hoy se compara con AYER A ESTA MISMA HORA, no con el día de ayer entero. Antes, a las 6 de la mañana con una venta
de $53.349 la tarjeta decía «▼ 86,3 % vs. ayer» en rojo (ayer había cerrado en $389.000): una falsa alarma todas las mañanas. Números hechos a mano; la base se simula.
"""
import os
from datetime import datetime

import pytest

import analisis_stock
import resumen_semanal
from utils import ARGENTINA

AHORA = datetime(2030, 3, 20, 6, 30, tzinfo=ARGENTINA)                          # miércoles, 6:30 de la mañana


class _Cursor:
    def __init__(self, *fetchone):
        self.respuestas = list(fetchone)
        self.llamadas = []

    def execute(self, sql, params=None):
        self.llamadas.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def _sin_stock(monkeypatch):
    monkeypatch.setattr(analisis_stock, "evaluar_cobertura_variantes", lambda cursor: [])
    monkeypatch.setattr(analisis_stock, "obtener_variantes_en_riesgo", lambda cursor: [{}, {}])


def _resumen(fact_hoy, fact_ayer_a_esta_hora, ordenes=1, unidades=1, top="Campera Negra", incidencias=0):
    cursor = _Cursor((fact_hoy, ordenes, unidades), (fact_ayer_a_esta_hora,), (top, unidades) if top else None, (incidencias,))
    return resumen_semanal.obtener_datos_resumen_diario(cursor, AHORA), cursor


def test_a_la_manana_se_compara_con_ayer_hasta_esa_misma_hora_no_con_el_dia_entero():
    datos, cursor = _resumen(53349, 40000)
    inicio, corte = cursor.llamadas[1][1]
    assert inicio == datetime(2030, 3, 19, 0, 0) and corte == datetime(2030, 3, 19, 6, 30)       # ayer de 00:00 a las 6:30, sin zona
    assert "BETWEEN" in cursor.llamadas[1][0] and "fecha_venta" in cursor.llamadas[1][0]
    assert datos["variacion_pct"] == 33.4                                                       # (53.349 − 40.000) / 40.000


def test_si_ayer_a_esta_hora_todavia_no_habia_vendido_no_hay_porcentaje_ni_flecha():
    datos, _ = _resumen(53349, 0)
    assert datos["variacion_pct"] is None                                                       # nada contra qué comparar: la tarjeta no pinta una flecha


def test_una_baja_real_contra_ayer_a_la_misma_hora_si_se_muestra():
    datos, _ = _resumen(20000, 80000)
    assert datos["variacion_pct"] == -75.0


def test_el_resumen_trae_lo_de_hoy_el_modelo_top_y_lo_demas():
    datos, cursor = _resumen(53349, 40000, ordenes=2, unidades=3, top="Campera Negra", incidencias=4)
    assert datos["ordenes"] == 2 and datos["unidades"] == 3 and datos["modelo_top"] == "Campera Negra"
    assert datos["facturado_formateado"] == "53.349"
    assert datos["variantes_clave_agotadas"] == 0 and datos["en_riesgo_stock"] == 2 and datos["incidencias_abiertas"] == 4
    assert cursor.llamadas[0][1] == ("2030-03-20",) and cursor.llamadas[2][1] == ("2030-03-20",)  # lo de hoy es el día de hoy, en hora argentina


def test_sin_ventas_hoy_no_hay_modelo_top():
    datos, _ = _resumen(0, 40000, ordenes=0, unidades=0, top=None)
    assert datos["modelo_top"] is None and datos["variacion_pct"] == -100.0


def test_el_cartel_de_la_tarjeta_dice_a_esta_hora():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "dashboard_personalizable.html")
    html = open(ruta, encoding="utf-8").read()
    assert "vs. ayer a esta hora" in html and "vs. ayer</span>" not in html

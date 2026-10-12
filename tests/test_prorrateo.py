"""
Prorrateo de gastos recurrentes (utils.prorratear_mensual) y el reporte fiscal anual que lo usa.
Un gasto mensual cuenta EXACTAMENTE su monto en un mes completo (de 28, 29, 30 o 31 días) y, en un período más corto, la parte proporcional de los días de cada mes que toca.
Antes se dividía siempre por 30: un alquiler de $150.000 figuraba como $155.000 en octubre, $140.000 en febrero y un año entero sumaba 12,17 meses (un contador lo vería de inmediato).
"""
from datetime import date

import pytest

import reporte_fiscal
from utils import prorratear_mensual

SIN_FIN = None
ENERO_1 = date(2026, 1, 1)


@pytest.mark.parametrize("desde, hasta", [
    (date(2026, 10, 1), date(2026, 10, 31)),          # 31 días
    (date(2026, 9, 1), date(2026, 9, 30)),            # 30
    (date(2026, 2, 1), date(2026, 2, 28)),            # 28
    (date(2028, 2, 1), date(2028, 2, 29)),            # 29 (bisiesto)
    (date(2026, 12, 1), date(2026, 12, 31)),
])
def test_un_mes_completo_vale_exactamente_el_monto(desde, hasta):
    assert prorratear_mensual(150000, ENERO_1, SIN_FIN, desde, hasta) == 150000.0


def test_los_dias_sueltos_valen_el_monto_dividido_los_dias_de_su_mes():
    assert prorratear_mensual(150000, ENERO_1, SIN_FIN, date(2026, 9, 1), date(2026, 9, 14)) == 70000.0                 # 14 de 30
    assert prorratear_mensual(150000, ENERO_1, SIN_FIN, date(2026, 10, 1), date(2026, 10, 14)) == round(150000 * 14 / 31, 2)   # 14 de 31
    assert prorratear_mensual(31000, ENERO_1, SIN_FIN, date(2026, 10, 7), date(2026, 10, 7)) == 1000.0                  # un solo día de octubre: 31.000 ÷ 31


def test_un_periodo_que_cruza_de_mes_suma_cada_tramo_con_los_dias_de_su_mes():
    # 20 al 30 de septiembre (11 días de 30) + 1 al 10 de octubre (10 días de 31)
    esperado = round(90000 * 11 / 30 + 90000 * 10 / 31, 2)
    assert prorratear_mensual(90000, ENERO_1, SIN_FIN, date(2026, 9, 20), date(2026, 10, 10)) == esperado


def test_un_gasto_que_empieza_o_termina_en_medio_del_periodo_cuenta_solo_sus_dias():
    assert prorratear_mensual(30000, date(2026, 9, 21), SIN_FIN, date(2026, 9, 1), date(2026, 9, 30)) == 10000.0        # del 21 al 30: 10 de 30
    assert prorratear_mensual(30000, ENERO_1, date(2026, 9, 10), date(2026, 9, 1), date(2026, 9, 30)) == 10000.0         # termina el 10: 10 de 30
    assert prorratear_mensual(30000, date(2026, 9, 8), date(2026, 9, 10), date(2026, 9, 1), date(2026, 9, 30)) == 3000.0     # vive 3 días
    assert prorratear_mensual(30000, date(2026, 9, 30), SIN_FIN, date(2026, 9, 1), date(2026, 9, 30)) == 1000.0          # arranca el último día: cuenta ese día
    assert prorratear_mensual(30000, ENERO_1, date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 30)) == 1000.0           # termina el primer día: cuenta ese día


def test_fuera_del_periodo_no_cuenta_nada():
    assert prorratear_mensual(30000, ENERO_1, date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 30)) == 0.0            # terminó antes
    assert prorratear_mensual(30000, date(2026, 10, 1), SIN_FIN, date(2026, 9, 1), date(2026, 9, 30)) == 0.0            # empieza después
    assert prorratear_mensual(30000, ENERO_1, SIN_FIN, date(2026, 9, 30), date(2026, 9, 1)) == 0.0                      # período al revés: nada


def test_un_anio_entero_suma_doce_meses_exactos_no_doce_con_diecisiete():
    total = prorratear_mensual(100000, ENERO_1, SIN_FIN, date(2026, 1, 1), date(2026, 12, 31))
    assert total == pytest.approx(1_200_000, abs=0.05)                                                  # (antes: 1.216.667 por dividir siempre por 30)
    assert sum(prorratear_mensual(100000, ENERO_1, SIN_FIN, date(2026, m, 1), date(2026, m, 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31)) for m in range(1, 13)) == 1_200_000.0


def test_el_resultado_va_redondeado_a_centavos():
    r = prorratear_mensual(100, ENERO_1, SIN_FIN, date(2026, 10, 1), date(2026, 10, 3))                  # 100 × 3/31 = 9,677…
    assert r == 9.68


# ── El reporte fiscal anual ─────────────────────────────────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, respuestas):
        self.respuestas, self.actual = respuestas, []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.actual = next((v for k, v in self.respuestas.items() if k in sql), [])

    def fetchall(self):
        return self.actual


class _Conexion:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cursor


def _reporte(monkeypatch, gastos, ventas=(), fabricacion=(), costos_fab=()):
    cursor = _Cursor({"FROM productos_padre": list(costos_fab), "COALESCE(SUM(precio_venta * cantidad), 0)": list(ventas),
                      "SUM(cantidad)::int": list(fabricacion), "FROM gastos_operativos": list(gastos)})
    monkeypatch.setattr(reporte_fiscal.db, "conexion_usuario", lambda u, c=None: _Conexion(cursor))
    return {m["mes"]: m for m in reporte_fiscal.calcular_reporte_anual(1, 2026, 7)}


def test_un_gasto_mensual_suma_su_monto_en_cada_mes_y_doce_veces_en_el_anio(monkeypatch):
    meses = _reporte(monkeypatch, [(150000, date(2025, 6, 1), True, None)])                             # alquiler vigente desde antes del año, sin fin
    assert all(meses[m]["gastos"] == 150000.0 for m in range(1, 13))                                     # incluso febrero y los de 31 días
    assert sum(m["gastos"] for m in meses.values()) == 1_800_000.0


def test_un_gasto_que_empieza_y_termina_en_medio_del_anio_cuenta_sus_dias(monkeypatch):
    # desde el 10/03 hasta el 20/05: marzo del 10 al 31 (22 de 31), abril entero, mayo del 1 al 20 (20 de 31)
    meses = _reporte(monkeypatch, [(31000, date(2026, 3, 10), True, date(2026, 5, 20))])
    assert (meses[2]["gastos"], meses[3]["gastos"], meses[4]["gastos"], meses[5]["gastos"], meses[6]["gastos"]) == (0.0, 22000.0, 31000.0, 20000.0, 0.0)


def test_un_gasto_unico_va_al_mes_en_que_cae_y_uno_de_otro_anio_no_cuenta(monkeypatch):
    meses = _reporte(monkeypatch, [(5000, date(2026, 6, 15), False, None), (9000, date(2024, 3, 1), False, None)])
    assert meses[6]["gastos"] == 5000.0 and sum(m["gastos"] for m in meses.values()) == 5000.0


def test_la_ganancia_estimada_del_mes_resta_cargos_gastos_y_costo_de_fabricacion(monkeypatch):
    # junio: facturó 100.000, comisiones 15.000, envíos 8.000, 12 unidades (10 del MLA1 a $2.000 y 2 del MLA2 a $500) y un gasto de 5.000
    meses = _reporte(monkeypatch, [(5000, date(2026, 6, 15), False, None)],
                     ventas=[(6, 100000, 15000, 8000, 12, 9, 1200)], fabricacion=[(6, "MLA1", 10), (6, "MLA2", 2)], costos_fab=[("MLA1", 2000), ("MLA2", 500)])
    j = meses[6]
    assert j["costo_fabricacion"] == 21000.0 and j["cargos_totales"] == 23000.0 and j["retenciones"] == 1200.0 and j["ordenes"] == 9
    assert j["ganancia_estimada"] == 100000 - 23000 - 5000 - 21000 == 51000.0 and j["ganancia_f"] == "51.000"
    assert meses[7]["facturacion"] == 0.0 and meses[7]["ganancia_estimada"] == 0.0                         # un mes sin ventas ni gastos: todo cero, no falla


def test_el_reporte_tiene_los_doce_meses_con_sus_fechas():
    meses = reporte_fiscal.calcular_meses(2028)
    assert len(meses) == 12 and meses[1] == (date(2028, 2, 1), date(2028, 2, 29)) and meses[11] == (date(2028, 12, 1), date(2028, 12, 31))

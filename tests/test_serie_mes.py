from datetime import date

from dashboard import serie_acumulada


def test_el_acumulado_suma_dia_a_dia_y_repite_los_dias_sin_ventas():
    por_dia = {date(2026, 9, 1): 100.0, date(2026, 9, 3): 50.0, date(2026, 10, 1): 30.0, date(2026, 10, 2): 20.0}
    s = serie_acumulada(por_dia, date(2026, 10, 1), date(2026, 10, 3), date(2026, 9, 1), date(2026, 9, 5))
    assert s["actual"] == [30.0, 50.0, 50.0]                 # termina hoy
    assert s["anterior"] == [100.0, 100.0, 150.0, 150.0, 150.0]   # el mes anterior completo, hasta su último día


def test_sin_ventas_da_ceros_del_largo_correcto():
    s = serie_acumulada({}, date(2026, 10, 1), date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 30))
    assert s["actual"] == [0.0] and s["anterior"] == [0.0] * 30


def test_el_ultimo_valor_es_el_total_del_periodo():
    por_dia = {date(2026, 2, d): 10.0 for d in range(1, 29)}
    assert serie_acumulada(por_dia, date(2026, 3, 1), date(2026, 3, 1), date(2026, 2, 1), date(2026, 2, 28))["anterior"][-1] == 280.0

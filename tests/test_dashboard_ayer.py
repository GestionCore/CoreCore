"""Por la mañana el Dashboard compara con AYER A ESTA MISMA HORA (contra el promedio del día entero cualquier mañana parece floja)."""
from datetime import datetime, timedelta, timezone

import dashboard as d

ARG = timezone(timedelta(hours=-3))
AHORA = datetime(2026, 10, 2, 11, 30, tzinfo=ARG)           # viernes 11:30


def _venta(momento, ganancia):
    return {"momento": momento, "raw": {"ganancia_neta": ganancia}}


def test_suma_solo_lo_de_ayer_hasta_esta_hora():
    ventas = [
        _venta("2026-10-01T00:05", 1000.0),      # ayer, madrugada: entra
        _venta("2026-10-01T11:30", 500.0),       # ayer, justo a esta hora: entra
        _venta("2026-10-01T11:31", 7000.0),      # ayer, un minuto después: no
        _venta("2026-10-01T18:00", 9000.0),      # ayer, tarde: no
        _venta("2026-10-02T09:00", 300.0),       # hoy: no
        _venta("2026-09-30T10:00", 4000.0),      # anteayer: no
    ]
    assert d.ganancia_de_ayer_hasta_la_hora(ventas, AHORA) == (1500.0, 2)


def test_una_perdida_de_ayer_resta():
    assert d.ganancia_de_ayer_hasta_la_hora([_venta("2026-10-01T09:00", 800.0), _venta("2026-10-01T10:00", -300.0)], AHORA) == (500.0, 2)


def test_sin_ventas_o_sin_momento_da_cero():
    assert d.ganancia_de_ayer_hasta_la_hora([], AHORA) == (0.0, 0)
    assert d.ganancia_de_ayer_hasta_la_hora([_venta(None, 100.0), {"raw": {"ganancia_neta": 5}}], AHORA) == (0.0, 0)

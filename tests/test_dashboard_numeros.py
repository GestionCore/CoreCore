"""
Números del Dashboard (dashboard.py): cómo viene el mes y a cuánto llegaría (proyección lineal), la serie acumulada contra el mes anterior, la tendencia de 14 días y el ticker de la barra superior.
Cálculos a mano; la base y la fecha están simuladas.
"""
from datetime import date, datetime, timedelta

import dashboard
from utils import ARGENTINA


class _Cursor:
    """Responde por fragmento de SQL; `respuestas` = {fragmento: valor o lista}. Para fetchone/fetchall devuelve lo que corresponde a la última consulta."""

    def __init__(self, respuestas):
        self.respuestas, self.actual, self.consultas = respuestas, None, []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.consultas.append((sql, params))
        self.actual = next((v for k, v in self.respuestas.items() if k in sql), None)

    def fetchone(self):
        return self.actual[0] if isinstance(self.actual, list) and self.actual and isinstance(self.actual[0], tuple) else self.actual

    def fetchall(self):
        return self.actual if isinstance(self.actual, list) else []


class _Conexion:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cursor


def _con(monkeypatch, respuestas):
    cursor = _Cursor(respuestas)
    monkeypatch.setattr(dashboard.db, "conexion_usuario", lambda u, c=None: _Conexion(cursor))
    return cursor


# ── Serie acumulada ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_serie_acumulada_suma_dia_por_dia_y_cada_mes_arranca_en_su_dia_1():
    por_dia = {date(2026, 10, 1): 100.0, date(2026, 10, 3): 50.5, date(2026, 9, 1): 10.0, date(2026, 9, 30): 5.0}
    s = dashboard.serie_acumulada(por_dia, date(2026, 10, 1), date(2026, 10, 4), date(2026, 9, 1), date(2026, 9, 30))
    assert s["actual"] == [100.0, 100.0, 150.5, 150.5]                          # llega hasta hoy, con los días sin ventas repitiendo el acumulado
    assert len(s["anterior"]) == 30 and s["anterior"][0] == 10.0 and s["anterior"][-1] == 15.0 and s["anterior"][1] == 10.0


# ── Cómo viene el mes ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _proyeccion(monkeypatch, hoy, totales, por_dia=()):
    _con(monkeypatch, {"FILTER": [totales], "GROUP BY fecha_venta": list(por_dia)})
    return dashboard.obtener_proyeccion_mes(1, 7, hoy=hoy)


def test_proyeccion_lineal_del_mes_y_comparacion_con_el_anterior(monkeypatch):
    # 15 de octubre: lleva $150.000 (30 u.); septiembre completo $400.000 y hasta el 15 de septiembre $180.000
    r = _proyeccion(monkeypatch, date(2026, 10, 15), (150000, 30, 400000, 180000, 90))
    assert r["dia"] == 15 and r["dias_mes"] == 31 and r["avance_pct"] == 48
    assert r["facturado_raw"] == 150000.0 and r["unidades"] == 30
    assert r["proyectado_raw"] == round(150000 / 15 * 31, 2) == 310000.0                          # ritmo diario × días del mes
    assert r["vs_mismo_punto"] == -16.7                                                              # (150.000 − 180.000) ÷ 180.000
    assert r["vs_mes_anterior"] == -22.5                                                             # (310.000 − 400.000) ÷ 400.000
    assert r["mes_nombre"] == "octubre" and r["mes_anterior_nombre"] == "septiembre" and r["pocos_dias"] is False
    assert r["facturado"] == "150.000" and r["proyectado"] == "310.000" and r["mes_anterior"] == "400.000" and r["mismo_punto"] == "180.000"


def test_con_menos_de_tres_dias_no_se_proyecta(monkeypatch):
    r = _proyeccion(monkeypatch, date(2026, 10, 2), (20000, 4, 400000, 25000, 90))
    assert r["pocos_dias"] is True and r["proyectado"] is None and r["proyectado_raw"] is None and r["vs_mes_anterior"] is None
    assert r["vs_mismo_punto"] == -20.0                                                              # la comparación punto a punto sí se hace
    assert _proyeccion(monkeypatch, date(2026, 10, 3), (30000, 5, 400000, 25000, 90))["proyectado_raw"] == round(30000 / 3 * 31, 2)       # desde el día 3 ya hay ritmo


def test_sin_ventas_este_mes_ni_el_anterior_no_hay_nada_que_mostrar(monkeypatch):
    assert _proyeccion(monkeypatch, date(2026, 10, 15), (0, 0, 0, 0, 0)) is None


def test_sin_mes_anterior_no_se_inventan_porcentajes(monkeypatch):
    r = _proyeccion(monkeypatch, date(2026, 10, 15), (150000, 30, 0, 0, 0))
    assert r["vs_mismo_punto"] is None and r["vs_mes_anterior"] is None and r["mes_anterior_raw"] == 0.0


def test_los_bordes_del_mes_anterior_marzo_febrero_y_enero(monkeypatch):
    cursor = _con(monkeypatch, {"FILTER": [(1000, 1, 2000, 1500, 2)], "GROUP BY fecha_venta": []})
    dashboard.obtener_proyeccion_mes(1, 7, hoy=date(2026, 3, 31))                                    # febrero tiene 28: «el mismo punto» es su último día, no un día que no existe
    assert cursor.consultas[0][1]["mp"] == date(2026, 2, 28) and cursor.consultas[0][1]["ia"] == date(2026, 2, 1)
    dashboard.obtener_proyeccion_mes(1, 7, hoy=date(2028, 3, 10))                                    # 2028 es bisiesto
    assert cursor.consultas[2][1]["fa"] == date(2028, 2, 29) and cursor.consultas[2][1]["mp"] == date(2028, 2, 10)
    r = dashboard.obtener_proyeccion_mes(1, 7, hoy=date(2026, 1, 20))                                # enero mira diciembre del año anterior
    assert r["mes_anterior_nombre"] == "diciembre" and cursor.consultas[4][1]["ia"] == date(2025, 12, 1)


def test_la_consulta_solo_cuenta_ventas_de_mercado_libre_vivas(monkeypatch):
    cursor = _con(monkeypatch, {"FILTER": [(1, 1, 1, 1, 1)], "GROUP BY fecha_venta": []})
    dashboard.obtener_proyeccion_mes(1, 7, hoy=date(2026, 10, 15))
    assert all("origen = 'meli' AND eliminado_en IS NULL" in sql for sql, _ in cursor.consultas)


# ── Tendencia de 14 días ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_tendencia_rellena_con_cero_los_dias_sin_ventas_y_promedia_sobre_todos_los_dias(monkeypatch):
    hoy = date(2026, 10, 14)
    monkeypatch.setattr(dashboard, "hoy_argentina", lambda: hoy)
    _con(monkeypatch, {"GROUP BY fecha_venta": [(date(2026, 10, 14), 14000), (date(2026, 10, 1), 7000.4)]})
    r = dashboard.obtener_tendencia_ventas(1, 7)
    assert len(r["serie"]) == 14 and r["serie"][0] == {"fecha": "01/10", "facturado": 7000.4} and r["serie"][-1] == {"fecha": "14/10", "facturado": 14000.0}
    assert sum(1 for p in r["serie"] if p["facturado"] == 0) == 12
    assert r["total_formateado"] == "21.000" and r["promedio_diario_formateado"] == "1.500"          # 21.000,4 ÷ 14 = 1.500,03: el promedio cuenta TODOS los días


def test_la_tendencia_sin_ventas_da_todo_cero(monkeypatch):
    monkeypatch.setattr(dashboard, "hoy_argentina", lambda: date(2026, 10, 14))
    _con(monkeypatch, {"GROUP BY fecha_venta": []})
    r = dashboard.obtener_tendencia_ventas(1, 7, dias=7)
    assert len(r["serie"]) == 7 and r["total_formateado"] == "0" and r["promedio_diario_formateado"] == "0"


# ── Preguntas y publicaciones sin stock ─────────────────────────────────────────────────────────────────────────────────────

def test_cuenta_preguntas_sin_responder_y_publicaciones_activas_sin_una_unidad():
    class _C:
        def __init__(self):
            self.resp = [(3,), (2,)]

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return self.resp.pop(0)
    assert dashboard.contar_preguntas_y_sin_stock(_C()) == (3, 2)


# ── El ticker de la barra superior ──────────────────────────────────────────────────────────────────────────────────────────

def test_el_ticker_arma_lo_de_hoy_lo_que_falta_acreditar_y_los_avisos(monkeypatch):
    monkeypatch.setattr(dashboard.salud_cuenta, "calcular_score_salud", lambda cursor: {"score": 72, "etiqueta": "Bien", "detalle": ["-15 por 1 reclamo activo"]})
    monkeypatch.setattr(dashboard, "contar_preguntas_y_sin_stock", lambda cursor: (4, 2))
    _con(monkeypatch, {
        "COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta": [(168548, 5)],
        "WHERE fecha_liberacion = ": [(1250.4,)],
        "GROUP BY fecha_liberacion": [(date(2026, 10, 9), 8000)],
        "WHERE fecha_liberacion >= %s": [(50300,)],
        "ORDER BY hora_venta DESC": [("Campera Negra", 1, 42990, datetime(2026, 10, 8, 14, 5)), ("Termo", 2, 15000, "09:30:00")],
        "FROM incidencias_posventa": [(2, 3, 1)],
        "SELECT racha_dias": [(6,)],
    })
    t = dashboard.obtener_ticker(1, 7)
    assert t["ventas_hoy"] == 5 and t["facturado_hoy"] == "168.548"
    assert t["liberacion_manana"] == "1.250" and t["proxima_liberacion"] == {"fecha": "09/10", "monto": "8.000"}
    assert t["a_liberar_total"] == "50.300" and t["hay_liberaciones"] is True
    assert (t["incidencias_activas"], t["devoluciones_activas"], t["reclamos_sin_impacto"]) == (2, 3, 1)       # reclamos que afectan, devoluciones y reclamos que no afectan, por separado
    assert t["salud_score"] == 72 and t["salud_etiqueta"] == "Bien" and t["racha_dias"] == 6
    assert t["ventas_hoy_detalle"] == [{"titulo": "Campera Negra", "cantidad": 1, "precio_formateado": "42.990", "hora": "14:05"}, {"titulo": "Termo", "cantidad": 2, "precio_formateado": "15.000", "hora": "09:30"}]
    assert t["avisos"]["total"] == 2 + 4 + 2 + 3 and [a["clave"] for a in t["avisos"]["items"]] == ["reclamos", "preguntas", "sin_stock", "devoluciones"]


def test_el_ticker_sin_nada_acreditar_ni_vendido_no_inventa_datos(monkeypatch):
    monkeypatch.setattr(dashboard.salud_cuenta, "calcular_score_salud", lambda cursor: {"score": 100, "etiqueta": "Muy bien", "detalle": []})
    monkeypatch.setattr(dashboard, "contar_preguntas_y_sin_stock", lambda cursor: (0, 0))
    _con(monkeypatch, {
        "COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta": [(0, 0)], "WHERE fecha_liberacion = ": [(None,)], "GROUP BY fecha_liberacion": [],
        "WHERE fecha_liberacion >= %s": [(None,)], "ORDER BY hora_venta DESC": [], "FROM incidencias_posventa": [(0, 0, 0)], "SELECT racha_dias": [(None,)],
    })
    t = dashboard.obtener_ticker(1, 7)
    assert t["facturado_hoy"] == "0" and t["proxima_liberacion"] is None and t["hay_liberaciones"] is False and t["racha_dias"] == 0
    assert t["ventas_hoy_detalle"] == [] and t["avisos"] == {"total": 0, "items": []}


def test_el_ticker_usa_el_dia_de_argentina(monkeypatch):
    """«Hoy» es el día en Argentina aunque el servidor corra en UTC: se consulta con la fecha de ARGENTINA."""
    monkeypatch.setattr(dashboard.salud_cuenta, "calcular_score_salud", lambda cursor: {"score": 100, "etiqueta": "Muy bien", "detalle": []})
    monkeypatch.setattr(dashboard, "contar_preguntas_y_sin_stock", lambda cursor: (0, 0))
    cursor = _con(monkeypatch, {"COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta": [(0, 0)], "WHERE fecha_liberacion = ": [(0,)], "GROUP BY fecha_liberacion": [],
                                "WHERE fecha_liberacion >= %s": [(0,)], "ORDER BY hora_venta DESC": [], "FROM incidencias_posventa": [(0, 0, 0)], "SELECT racha_dias": [(0,)]})
    dashboard.obtener_ticker(1, 7)
    hoy_ar = datetime.now(ARGENTINA)
    consultado = cursor.consultas[0][1][0]
    assert consultado in ((hoy_ar).strftime("%Y-%m-%d"), (hoy_ar - timedelta(minutes=1)).strftime("%Y-%m-%d"))       # (tolera cambiar de día entre las dos lecturas)
    assert date.fromisoformat(cursor.consultas[1][1][0]) - date.fromisoformat(consultado) == timedelta(days=1)                          # «mañana» es el día siguiente a ese hoy

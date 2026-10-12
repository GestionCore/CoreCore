"""
costos.py: gastos operativos (los recurrentes se prorratean por día del período: monto × días/30), ganancia estimada por producto y cobertura de costos de fabricación.
Entra en Ganancia Real (costos fijos del punto de equilibrio) y en el aviso de «ganancia inflada». Números calculados a mano; la base está simulada.
"""
from datetime import date

import pytest

import costos


# ── Cuántos días de un gasto caen dentro del período ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inicio, fin, desde, hasta, esperado", [
    (date(2026, 1, 1), None, date(2026, 9, 1), date(2026, 9, 14), 14),                       # arrancó antes y sigue vigente: todo el período
    (date(2026, 9, 5), None, date(2026, 9, 1), date(2026, 9, 14), 10),                       # arranca el 5: 5 al 14 inclusive = 10 días
    (date(2026, 9, 14), None, date(2026, 9, 1), date(2026, 9, 14), 1),                       # arranca el último día: cuenta ese día
    (date(2026, 8, 1), date(2026, 9, 3), date(2026, 9, 1), date(2026, 9, 14), 3),            # termina el 3: 1 al 3 inclusive
    (date(2026, 8, 1), date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 14), 1),            # termina el primer día del período
    (date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 14), 0),           # terminó antes: nada
    (date(2026, 9, 15), None, date(2026, 9, 1), date(2026, 9, 14), 0),                       # empieza después: nada
    (date(2026, 9, 3), date(2026, 9, 6), date(2026, 9, 1), date(2026, 9, 30), 4),            # adentro del período: sus propios 4 días
    (date(2026, 8, 1), date(2026, 10, 30), date(2026, 9, 1), date(2026, 9, 30), 30),         # cubre todo el mes
])
def test_dias_de_solapamiento(inicio, fin, desde, hasta, esperado):
    assert costos._dias_de_solapamiento(inicio, fin, desde, hasta) == esperado


# ── Base simulada ───────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Cursor:
    """Responde por el texto del SQL; `respuestas` = {fragmento: filas}."""

    def __init__(self, respuestas):
        self.respuestas, self.filas, self.ejecutadas = respuestas, [], []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.ejecutadas.append((sql, params))
        for fragmento, filas in self.respuestas.items():
            if fragmento in sql:
                self.filas = filas
                return
        self.filas = []

    def fetchall(self):
        return self.filas

    def fetchone(self):
        return self.filas[0] if self.filas else None


class _Conexion:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, row_factory=None):
        return self._cursor


def _gasto(id_, concepto, categoria, monto, fecha, recurrente=False, fecha_fin=None):
    return {"id": id_, "concepto": concepto, "categoria": categoria, "monto": monto, "fecha": fecha, "recurrente": recurrente, "fecha_fin": fecha_fin}


def _producto(id_meli, titulo, costo, precio, recibis, estado="active"):
    return {"id_meli": id_meli, "titulo": titulo, "precio_costo": costo, "estado": estado, "thumbnail": None, "precio": precio, "recibis_estimado": recibis}


def _datos(monkeypatch, gastos, productos, envios, desde="2026-09-01", hasta="2026-09-14"):
    cursor = _Cursor({"FROM gastos_operativos": gastos, "FROM productos_padre": productos, "AVG(costo_envio)": envios})
    monkeypatch.setattr(costos.db, "conexion_usuario", lambda usuario, cuenta=None: _Conexion(cursor))
    return costos.obtener_datos_costos(1, desde, hasta, 7), cursor


# ── Gastos ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_los_gastos_se_separan_en_fijos_y_variables_y_los_recurrentes_se_prorratean_por_dia(monkeypatch):
    gastos = [
        _gasto(1, "Alquiler", "fijo", 150000, date(2026, 1, 1), recurrente=True),                           # todo el período (14 días): 150.000 × 14/30 = 70.000
        _gasto(2, "Contador", "fijo", 30000, date(2026, 9, 8), recurrente=True, fecha_fin=date(2026, 9, 10)),   # 8 al 10 = 3 días: 30.000 × 3/30 = 3.000
        _gasto(3, "Embalaje", "variable", 2500.4, date(2026, 9, 5)),                                         # puntual: entra entero
        _gasto(4, "Mantenimiento", "fijo", 10000, date(2026, 9, 2)),                                         # puntual fijo: entra entero
    ]
    (lista, stats, _), _c = _datos(monkeypatch, gastos, [], [])
    assert stats["fijos_raw"] == 70000 + 3000 + 10000 and stats["variables_raw"] == 2500.4
    assert stats["fijos"] == "83.000" and stats["variables"] == "2.500" and stats["total"] == "85.500"      # el texto va sin centavos
    por_id = {g["id"]: g for g in lista}
    assert por_id[1]["monto_formateado"] == "70.000" and por_id[1]["monto_mensual_formateado"] == "150.000" and por_id[1]["recurrente"] is True
    assert por_id[3]["monto_mensual_formateado"] is None and por_id[3]["fecha"] == "2026-09-05"


def test_un_periodo_de_un_mes_corrido_prorratea_con_30_dias_de_referencia(monkeypatch):
    """Decisión documentada (DIAS_MES_REFERENCIA = 30): un período de 31 días cuenta 31/30 del gasto mensual."""
    (_, stats, _), _c = _datos(monkeypatch, [_gasto(1, "Alquiler", "fijo", 30000, date(2026, 1, 1), recurrente=True)], [], [], desde="2026-10-01", hasta="2026-10-31")
    assert stats["fijos_raw"] == 31000.0


def test_la_consulta_trae_los_recurrentes_vigentes_y_los_puntuales_del_periodo(monkeypatch):
    _, cursor = _datos(monkeypatch, [], [], [])
    sql, params = next(e for e in cursor.ejecutadas if "FROM gastos_operativos" in e[0])
    assert "recurrente = false AND fecha BETWEEN %s AND %s" in sql and "recurrente = true AND fecha <= %s AND (fecha_fin IS NULL OR fecha_fin >= %s)" in sql
    assert params == ("2026-09-01", "2026-09-14", "2026-09-14", "2026-09-01")


def test_sin_gastos_los_totales_son_cero(monkeypatch):
    (lista, stats, productos), _c = _datos(monkeypatch, [], [], [])
    assert lista == [] and productos == [] and stats["fijos_raw"] == 0 and stats["variables_raw"] == 0 and stats["total"] == "0"


# ── Ganancia estimada por producto ──────────────────────────────────────────────────────────────────────────────────────────

def test_la_ganancia_estimada_resta_comision_envio_y_costo(monkeypatch):
    # precio 10.000, MeLi deposita 8.200 → comisión 1.800; envío promedio 1.500; costo de fabricación 4.000
    # ganancia = 10.000 − 1.800 − 1.500 − 4.000 = 2.700
    productos = [_producto("MLA1", "Campera Negra Talle M", 4000, 10000, 8200)]
    (_, _, lista), _c = _datos(monkeypatch, [], productos, [{"id_meli": "MLA1", "envio_promedio": 1500}])
    p = lista[0]
    assert p["comision"] == 1800.0 and p["envio"] == 1500.0 and p["ganancia_neta_formateada"] == "2.700" and p["ganancia_negativa"] is False
    assert p["segmentos_pct"] == {"costo": 40.0, "envio": 15.0, "comision": 18.0, "ganancia": 27.0}                     # las 4 partes del precio suman 100
    assert sum(p["segmentos_pct"].values()) == 100.0
    assert p["modelo"] == "Campera Negra" and p["talle"] == "M"                                                        # el modelo no lleva el talle: los talles se agrupan


def test_un_producto_que_pierde_plata_se_marca_y_su_tajada_de_ganancia_es_cero(monkeypatch):
    productos = [_producto("MLA2", "Buzo", 9000, 10000, 8200)]                                                          # 10.000 − 1.800 − 0 − 9.000 = −800
    (_, _, lista), _c = _datos(monkeypatch, [], productos, [])
    p = lista[0]
    assert p["ganancia_neta_formateada"] == "-800" and p["ganancia_negativa"] is True and p["segmentos_pct"]["ganancia"] == 0.0


def test_sin_precio_neto_estimado_no_se_inventa_una_ganancia(monkeypatch):
    productos = [_producto("MLA3", "Gorra", 500, 3000, None), _producto("MLA4", "Medias", 0, 0, 0)]
    (_, _, lista), _c = _datos(monkeypatch, [], productos, [])
    for p in lista:
        assert p["ganancia_neta_formateada"] is None and p["segmentos_pct"] is None and p["ganancia_negativa"] is False and p["comision"] is None
    assert lista[1]["precio_formateado"] is None                                                                        # precio 0: no se muestra «$0»


def test_el_costo_de_fabricacion_en_cero_queda_como_cero_no_como_dato_faltante(monkeypatch):
    (_, _, lista), _c = _datos(monkeypatch, [], [_producto("MLA5", "Remera", None, 5000, 4000)], [])
    assert lista[0]["precio_costo"] == 0.0 and lista[0]["precio_costo_formateado"] == "0"


def test_sin_titulo_no_rompe(monkeypatch):
    (_, _, lista), _c = _datos(monkeypatch, [], [_producto("MLA6", None, 100, 1000, 800)], [])
    assert lista[0]["modelo"] == "Sin nombre" and lista[0]["talle"] == "Único"


# ── Cuánto de lo facturado no tiene costo cargado ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("facturado, sin_costo, publicaciones, pct, avisar", [
    (100000, 4900, 1, 4.9, False),               # por debajo del 5 %: no se avisa
    (100000, 5000, 2, 5.0, True),                # justo el umbral: se avisa
    (200000, 150000, 7, 75.0, True),
    (100000, 0, 0, 0.0, False),                  # todo con costo
    (0, 0, 0, 0.0, False),                       # sin ventas: nada que avisar (y sin dividir por cero)
])
def test_cobertura_de_costos(facturado, sin_costo, publicaciones, pct, avisar):
    cursor = _Cursor({"FROM ventas": [(facturado, sin_costo, publicaciones)]})
    r = costos.cobertura_de_costos(cursor, "2026-09-01", "2026-09-30")
    assert r == {"facturado": float(facturado), "sin_costo": float(sin_costo), "pct_sin_costo": pct, "publicaciones": publicaciones, "avisar": avisar}
    assert cursor.ejecutadas[0][1] == ("2026-09-01", "2026-09-30")


def test_la_cobertura_mide_por_plata_y_cuenta_costo_cero_como_sin_costo():
    cursor = _Cursor({"FROM ventas": [(None, None, None)]})
    assert costos.cobertura_de_costos(cursor, "a", "b")["pct_sin_costo"] == 0.0                                         # una base sin ventas devuelve NULL: no rompe
    sql = cursor.ejecutadas[0][0]
    assert "COALESCE(p.precio_costo, 0) <= 0" in sql                                                                    # costo vacío o en $0 = sin costo

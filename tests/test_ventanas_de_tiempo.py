"""
Ventanas de tiempo: cada comparación «últimos N días contra los N anteriores» usa N días COMPLETOS (sin hoy, que está a medias), del mismo largo y sin pisarse.
Antes: la alerta «Facturación cayó» y el puntaje de salud comparaban dos tramos de 8 días que se pisaban en un día (y la semana actual incluía hoy a medias, así que a la mañana podía
dar una caída de ~11 % sin que hubiera pasado nada); Promociones dividía 8 días entre 7 y contaba un día de más al medir el ritmo; las visitas «de 14 días» eran 15 contra 13.
Números hechos a mano. La base se simula.
"""
from datetime import date, timedelta

import pytest

import costos_chat
import enriquecimiento
import logros
import promociones
import salud_cuenta
import utils

HOY = date(2030, 3, 20)                                                        # un miércoles


class _Cursor:
    """Cursor falso: guarda cada consulta con sus parámetros y responde con lo armado a mano, en orden."""

    def __init__(self, *fetchone, fetchall=()):
        self.fetchone_respuestas, self.fetchall_respuestas = list(fetchone), list(fetchall)
        self.llamadas = []

    def execute(self, sql, params=None):
        self.llamadas.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.fetchone_respuestas.pop(0)

    def fetchall(self):
        return self.fetchall_respuestas.pop(0) if self.fetchall_respuestas else []


# ── Las dos semanas ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_las_semanas_son_de_7_dias_completos_seguidos_y_sin_hoy():
    (a_desde, a_hasta), (p_desde, p_hasta) = utils.semanas_completas(HOY)
    assert (a_desde, a_hasta) == (date(2030, 3, 13), date(2030, 3, 19))          # de hace 7 días a ayer
    assert (p_desde, p_hasta) == (date(2030, 3, 6), date(2030, 3, 12))           # de hace 14 a hace 8
    assert (a_hasta - a_desde).days + 1 == 7 == (p_hasta - p_desde).days + 1     # mismo largo
    assert p_hasta + timedelta(days=1) == a_desde and a_hasta < HOY               # una pegada a la otra, sin pisarse, y hoy afuera


def test_facturado_de_las_ultimas_semanas_consulta_las_dos_semanas_en_ese_orden():
    cursor = _Cursor((90000,), (120000.5,))
    assert utils.facturado_de_las_ultimas_semanas(cursor, HOY) == (90000.0, 120000.5)
    assert [p for _, p in cursor.llamadas] == [(date(2030, 3, 13), date(2030, 3, 19)), (date(2030, 3, 6), date(2030, 3, 12))]
    assert utils.facturado_de_las_ultimas_semanas(_Cursor((None,), (None,)), HOY) == (0.0, 0.0)          # sin ventas no es un error


# ── «Facturación cayó» ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("actual, anterior, hay_mision", [
    (80000, 100000, True),          # −20 %: justo el límite
    (79999, 100000, True),
    (80001, 100000, False),         # −19,999 %: no
    (150000, 100000, False),        # crece
    (0, 100000, True),              # se cayó a cero
    (50000, 0, False),              # no hay con qué comparar
])
def test_la_mision_de_caida_se_dispara_a_partir_de_20_por_ciento(actual, anterior, hay_mision):
    mision = logros._mision_facturacion_cae(_Cursor((actual,), (anterior,)))
    assert (mision is not None) is hay_mision


def test_la_mision_de_caida_dice_cuanto_cayo_y_compara_semanas_completas():
    mision = logros._mision_facturacion_cae(_Cursor((75000,), (100000,)))
    assert mision["id"] == "facturacion_cae" and mision["prioridad"] == "urgente"
    assert mision["titulo"] == "Facturación cayó 25% en la última semana"
    assert "$100.000 a $75.000" in mision["descripcion"] and "7 días completos" in mision["descripcion"]


def test_a_la_manana_hoy_no_arma_una_caida_falsa():
    """Ventas parejas de $100.000 por semana: ni hoy a medias ni el día repetido entre los tramos pueden restar nada."""
    (a_desde, a_hasta), (p_desde, p_hasta) = utils.semanas_completas(HOY)
    ventas = {a_desde + timedelta(days=i): 100000 / 7 for i in range(7)} | {p_desde + timedelta(days=i): 100000 / 7 for i in range(7)}
    ventas[HOY] = 500.0                                                          # hoy, a las 8 de la mañana, con una venta chica
    actual = sum(v for f, v in ventas.items() if a_desde <= f <= a_hasta)
    anterior = sum(v for f, v in ventas.items() if p_desde <= f <= p_hasta)
    assert logros._mision_facturacion_cae(_Cursor((actual,), (anterior,))) is None


def test_el_puntaje_de_salud_usa_las_mismas_semanas_completas(monkeypatch):
    monkeypatch.setattr(salud_cuenta.analisis_stock, "evaluar_cobertura_variantes", lambda cursor: [])
    visto = {}
    monkeypatch.setattr(salud_cuenta, "facturado_de_las_ultimas_semanas", lambda cursor: visto.setdefault("llamado", True) and (70000.0, 100000.0))

    class _C:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return (0,)

        def fetchall(self):
            return []
    r = salud_cuenta.calcular_score_salud(_C())
    assert visto["llamado"] and r["score"] == 85 and r["detalle"] == ["-15 por caída de facturación de -30% vs. la semana anterior"]


# ── Promociones ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(promociones, "hoy_argentina", lambda: HOY)


def test_el_ritmo_de_antes_son_los_7_dias_completos_anteriores_a_hoy(hoy_fijo):
    cursor = _Cursor((14,))                                                      # 14 unidades en 7 días
    promociones.registrar_inicio_promocion(cursor, 1, "MLA1", "Termo", 10000, 9000)
    consulta_ventas, params_ventas = cursor.llamadas[0]
    assert params_ventas == ("MLA1", "2030-03-13", "2030-03-19")                 # hoy (20/03) queda afuera
    insertar = cursor.llamadas[1][1]
    assert insertar[7] == 2.0 and insertar[5] == "2030-03-20"                    # 14 ÷ 7 = 2 por día; la promoción arranca hoy


def _impacto(monkeypatch, filas, ventas):
    monkeypatch.setattr(promociones, "hoy_argentina", lambda: HOY)
    monkeypatch.setattr(promociones.historial_precios, "ventas_diarias", lambda cursor, ids, desde, hasta: ventas)
    return promociones.obtener_impacto_promociones(_Cursor(fetchall=[filas]))


def _fila(id_meli, inicio, fin, previo, activo):
    return (1, id_meli, "Termo", 10000, 9000, inicio, fin, previo, activo, None)


def test_una_promocion_activa_mide_su_ritmo_con_dias_completos_y_sin_hoy(monkeypatch):
    # Arrancó hace 4 días (16/03): 3 + 3 + 3 + 3 en los 4 días completos (16 al 19) y 2 de hoy, que está a medias
    ventas = {"MLA1": [("2030-03-16", 3), ("2030-03-17", 3), ("2030-03-18", 3), ("2030-03-19", 3), ("2030-03-20", 2)]}
    r = _impacto(monkeypatch, [_fila("MLA1", date(2030, 3, 16), None, 2.0, True)], ventas)[0]
    assert r["dias_medidos"] == 4 and r["promedio_durante"] == 3.0 and r["variacion_pct"] == 50.0       # 12 ÷ 4 = 3 contra 2 de antes
    assert r["unidades_durante"] == 14                                                                   # «lo vendido hasta ahora» sí incluye hoy


def test_una_promocion_que_arranco_hoy_todavia_no_tiene_con_que_compararse(monkeypatch):
    ventas = {"MLA1": [("2030-03-20", 1)]}
    r = _impacto(monkeypatch, [_fila("MLA1", date(2030, 3, 20), None, 2.0, True)], ventas)[0]
    assert r["dias_medidos"] == 0 and r["variacion_pct"] is None and r["promedio_durante"] == 0.0 and r["unidades_durante"] == 1


def test_una_promocion_terminada_cuenta_del_primer_al_ultimo_dia(monkeypatch):
    ventas = {"MLA1": [("2030-03-10", 4), ("2030-03-11", 4), ("2030-03-12", 1), ("2030-03-13", 99)]}      # el 13 es después del fin
    r = _impacto(monkeypatch, [_fila("MLA1", date(2030, 3, 10), date(2030, 3, 12), 3.0, False)], ventas)[0]
    assert r["dias_medidos"] == 3 and r["promedio_durante"] == 3.0 and r["variacion_pct"] == 0.0         # 9 ÷ 3 días = 3 contra 3 de antes
    assert r["unidades_durante"] == 9


def test_sin_ritmo_de_antes_no_hay_variacion(monkeypatch):
    ventas = {"MLA1": [("2030-03-17", 5)]}
    r = _impacto(monkeypatch, [_fila("MLA1", date(2030, 3, 17), None, 0, True)], ventas)[0]
    assert r["variacion_pct"] is None and r["dias_medidos"] == 3


def test_los_candidatos_a_promocion_miden_14_dias_completos(hoy_fijo):
    # 70 unidades de stock y 14 vendidas en 14 días = 1 por día: alcanza para 70 días (≥ 20), o sea que rota lento y es candidata
    cursor = _Cursor(fetchall=[[("MLA1", "Termo", 10000, 4000, 70, None)], [("MLA1", 14)], []])
    sugeridos = promociones.sugerir_candidatos_promocion(cursor)
    assert cursor.llamadas[1][1] == ("2030-03-06", "2030-03-19")                  # de hace 14 días a ayer
    assert [s["id_meli"] for s in sugeridos] == ["MLA1"] and sugeridos[0]["capital_inmovilizado"] == 700000.0


def test_los_candidatos_no_incluyen_lo_que_ya_esta_en_promocion_ni_lo_que_rota_rapido(hoy_fijo):
    filas = [("MLA1", "Termo", 10000, 4000, 70, None), ("MLA2", "Taza", 5000, 1500, 10, None)]
    cursor = _Cursor(fetchall=[filas, [("MLA1", 14), ("MLA2", 14)], [("MLA1",)]])                          # MLA1 ya está en promoción; MLA2 alcanza para 10 días
    assert promociones.sugerir_candidatos_promocion(cursor) == []


# ── Visitas de 14 días ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _dias(desde, hasta, total=1):
    return [{"date": f"{desde + timedelta(days=i):%Y-%m-%d}T00:00:00.000-03:00", "total": total} for i in range((hasta - desde).days + 1)]


def test_cada_tramo_de_visitas_tiene_14_dias_exactos_incluyendo_hoy():
    dias = _dias(HOY - timedelta(days=27), HOY)                                    # 28 días terminando hoy, 1 visita por día
    assert enriquecimiento.visitas_por_tramo(dias, HOY) == (14, 14)


def test_si_mercado_libre_todavia_no_cuenta_hoy_los_tramos_siguen_siendo_de_14_dias():
    dias = _dias(HOY - timedelta(days=28), HOY - timedelta(days=1))                # 28 días terminando ayer
    assert enriquecimiento.visitas_por_tramo(dias, HOY) == (14, 14)


def test_las_visitas_reparten_cada_dia_en_el_tramo_que_le_toca():
    dias = _dias(HOY - timedelta(days=27), HOY - timedelta(days=14), total=2) + _dias(HOY - timedelta(days=13), HOY, total=5)
    assert enriquecimiento.visitas_por_tramo(dias, HOY) == (14 * 5, 14 * 2)        # 70 recientes, 28 de las anteriores


def test_una_respuesta_con_dias_salteados_no_corre_los_tramos():
    dias = _dias(HOY - timedelta(days=27), HOY - timedelta(days=10))               # la última visita fue hace 10 días: lo de hoy no se informa
    recientes, previas = enriquecimiento.visitas_por_tramo(dias, HOY)
    assert recientes == 5 and previas == 13                                        # el tramo reciente es de hace 14 a ayer (5 de esos días tienen dato: hace 14 a hace 10); el anterior, de hace 28 a hace 15 (los datos empiezan hace 27: 13 días)
    assert enriquecimiento.visitas_por_tramo([], HOY) == (0, 0)


def test_una_publicacion_nueva_con_pocos_dias_no_inventa_visitas_previas():
    assert enriquecimiento.visitas_por_tramo(_dias(HOY - timedelta(days=5), HOY, total=3), HOY) == (18, 0)


# ── Costos por chat: lo que se confirma se valida otra vez en el servidor ───────────────────────────────────────────────────────────────

class _Prestada:
    def __init__(self, ejecutadas):
        self.ejecutadas = ejecutadas

    def __enter__(self):
        ejecutadas = self.ejecutadas

        class _Conexion:
            def cursor(self):
                class _C:
                    def execute(self, sql, params=None):
                        ejecutadas.append((" ".join(sql.split()), params))
                return _C()
        return _Conexion()

    def __exit__(self, *a):
        return False


def _gasto(**cambios):
    base = {"concepto": "Alquiler", "monto": 150000, "categoria": "fijo", "recurrente": True, "fecha_desde": "2030-03-01", "fecha_fin": None}
    return {**base, **cambios}


def test_un_gasto_valido_se_guarda_con_el_concepto_limpio(monkeypatch):
    ejecutadas = []
    monkeypatch.setattr(costos_chat.db, "conexion_usuario", lambda u, c=None: _Prestada(ejecutadas))
    ok, resultado = costos_chat.confirmar_y_guardar(1, 7, [_gasto(concepto="  Alquiler del local  ")])
    assert ok and resultado == {"gastos": 1, "publicaciones": 0}
    assert ejecutadas[0][1] == (7, "Alquiler del local", "fijo", 150000.0, "2030-03-01", True, None)


@pytest.mark.parametrize("cambios, mensaje", [
    ({"monto": "nan"}, "mayor que cero"), ({"monto": float("inf")}, "mayor que cero"), ({"monto": -500}, "mayor que cero"), ({"monto": 0}, "mayor que cero"),
    ({"monto": 1e13}, "mayor que cero"), ({"monto": "abc"}, "formato inválido"),
    ({"concepto": ""}, "concepto"), ({"concepto": "   "}, "concepto"), ({"concepto": None}, "concepto"), ({"concepto": 123}, "concepto"),
    ({"fecha_desde": "01/03/2030"}, "formato inválido"), ({"fecha_fin": "2030-02-28"}, "anterior a la de inicio"),
    ({"categoria": "otro"}, "Categoría"),
])
def test_un_gasto_mal_formado_se_rechaza_y_no_se_escribe_nada(monkeypatch, cambios, mensaje):
    ejecutadas = []
    monkeypatch.setattr(costos_chat.db, "conexion_usuario", lambda u, c=None: _Prestada(ejecutadas))
    ok, texto = costos_chat.confirmar_y_guardar(1, 7, [_gasto(), _gasto(**cambios)])               # el primero está bien: tampoco se guarda
    assert not ok and mensaje in texto and ejecutadas == []


def test_un_gasto_que_termina_el_mismo_dia_que_empieza_es_valido(monkeypatch):
    ejecutadas = []
    monkeypatch.setattr(costos_chat.db, "conexion_usuario", lambda u, c=None: _Prestada(ejecutadas))
    assert costos_chat.confirmar_y_guardar(1, 7, [_gasto(fecha_fin="2030-03-01")])[0] is True


def test_un_concepto_muy_largo_se_corta_a_200_caracteres(monkeypatch):
    ejecutadas = []
    monkeypatch.setattr(costos_chat.db, "conexion_usuario", lambda u, c=None: _Prestada(ejecutadas))
    costos_chat.confirmar_y_guardar(1, 7, [_gasto(concepto="x" * 500)])
    assert len(ejecutadas[0][1][1]) == 200


def test_sin_nada_que_guardar_se_avisa():
    assert costos_chat.confirmar_y_guardar(1, 7, [], []) == (False, "Faltan datos en la propuesta.")


# ── Proyección del mes: hoy cuenta hasta la hora que es ─────────────────────────────────────────────────────────────────────────────────

def test_los_dias_que_lleva_el_mes_cuentan_hoy_hasta_esta_hora():
    import dashboard
    from datetime import datetime
    assert dashboard.dias_transcurridos_del_mes(date(2030, 3, 3), datetime(2030, 3, 3, 9, 0)) == 2.375               # 2 días enteros y 9 de 24 horas
    assert dashboard.dias_transcurridos_del_mes(date(2030, 3, 3), datetime(2030, 3, 3, 0, 0)) == 2.0
    assert dashboard.dias_transcurridos_del_mes(date(2030, 3, 3), datetime(2030, 3, 3, 23, 59, 59)) < 3.0
    assert dashboard.dias_transcurridos_del_mes(date(2030, 3, 3)) == 3.0                                                # sin hora (una fecha pedida a mano) hoy cuenta entero


def test_a_principios_de_mes_la_proyeccion_no_subestima_el_ritmo(monkeypatch):
    import dashboard
    from datetime import datetime
    from tests.test_dashboard_numeros import _con
    _con(monkeypatch, {"FILTER": [(23750, 10, 100000, 20000, 40)], "GROUP BY fecha_venta": []})
    r = dashboard.obtener_proyeccion_mes(1, 7, hoy=date(2030, 3, 3), ahora=datetime(2030, 3, 3, 9, 0))              # 23.750 en 2,375 días = 10.000 por día
    assert r["proyectado_raw"] == 310000.0                                                                               # × 31 días; dividiendo por 3 daba 245.416,67
    assert dashboard.dias_transcurridos_del_mes(date(2030, 3, 3), datetime(2030, 3, 3, 9, 0)) * 10000 == 23750.0

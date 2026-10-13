"""
Monitor en vivo (monitor_en_vivo.py) y costo de publicidad por unidad vendida (metricas.armar_cpa / calcular_cpa_real).
Números hechos a mano. Lo que toca la base corre contra la base real DENTRO de una transacción que se revierte (fecha lejana: no se mezcla con datos de verdad), y la
tabla de anotaciones se crea ahí adentro con la migración 0048 (así la prueba no depende de que esté aplicada).
"""
import json
import os
from datetime import date, datetime

import pytest

import ads
import metricas
import monitor_en_vivo as mon
from utils import ARGENTINA

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


def _t(h, m=0, dia=5):
    return datetime(2030, 3, dia, h, m, tzinfo=ARGENTINA)


# ── Curva por hora a partir de acumulados ────────────────────────────────────────────────────────────────────────────────────────────

def test_la_curva_reparte_lo_que_sumo_cada_intervalo_entre_las_horas_que_abarca():
    puntos = [(_t(10, 30), 100), (_t(11, 0), 160), (_t(11, 30), 220), (_t(12, 15), 235)]
    c = mon.curva_por_hora(puntos)
    assert (c[10]["valor"], c[10]["cubierta"]) == (60.0, 0.5)                       # 10:30 a 11:00: la mitad de la hora 10, todo lo que sumó
    assert (c[11]["valor"], c[11]["cubierta"]) == (70.0, 1.0)                       # 60 de 11:00 a 11:30 + 10 de los 15 que sumó de 11:30 a 12:15 (30 de esos 45 minutos caen en la hora 11)
    assert (c[12]["valor"], c[12]["cubierta"]) == (5.0, 0.25)                       # los 5 restantes, 15 minutos de la hora 12
    assert sum(f["valor"] for f in c) == 135 == 235 - 100                           # nada se pierde ni se inventa: lo de ANTES de la primera anotación no se le asigna a ninguna hora
    assert all(f["valor"] == 0 and f["cubierta"] == 0 for f in c if f["hora"] not in (10, 11, 12))


def test_un_acumulado_que_baja_no_resta_y_con_un_solo_punto_no_hay_curva():
    c = mon.curva_por_hora([(_t(9, 0), 100), (_t(9, 30), 90), (_t(10, 0), 120)])       # MeLi corrigió el número hacia abajo: esa baja vale 0, no -10
    assert c[9]["valor"] == 30.0 and c[9]["cubierta"] == 1.0
    assert all(f["valor"] == 0 for f in mon.curva_por_hora([(_t(9, 0), 50)])) and all(f["cubierta"] == 0 for f in mon.curva_por_hora([]))
    assert len(mon.curva_por_hora([])) == 24


def test_las_curvas_de_la_cuenta_son_la_suma_de_sus_campanas_y_la_que_falta_en_una_anotacion_vale_cero():
    a = [
        (_t(10, 0), "ads", "C1", {"nombre": "Camperas", "impresiones": 1000, "clics": 10, "costo": 100.0, "unidades": 0, "monto": 0}),
        (_t(10, 0), "visitas", "", {"visitas": 200}),
        (_t(11, 0), "ads", "C1", {"nombre": "Camperas", "impresiones": 1500, "clics": 16, "costo": 150.0, "unidades": 1, "monto": 50000}),
        (_t(11, 0), "ads", "C2", {"nombre": "Medias", "impresiones": 300, "clics": 3, "costo": 20.0, "unidades": 0, "monto": 0}),     # C2 aparece recién a las 11 (antes valía 0)
        (_t(11, 0), "visitas", "", {"visitas": 260}),
    ]
    r = mon.armar_curvas(a)
    assert r["anotaciones"] == 2 and r["desde"] == "10:00"
    assert r["curvas"]["C1"]["impresiones"][10]["valor"] == 500.0 and r["curvas"]["C1"]["clics"][10]["valor"] == 6.0 and r["curvas"]["C1"]["unidades"][10]["valor"] == 1.0
    assert r["curvas"]["C2"]["impresiones"][10]["valor"] == 300.0                      # de 10 a 11 pasó de 0 a 300
    assert r["curvas"]["*"]["impresiones"][10]["valor"] == 800.0 and r["curvas"]["*"]["clics"][10]["valor"] == 9.0 and r["curvas"]["*"]["costo"][10]["valor"] == 70.0
    assert r["curvas"]["*"]["nombre"] == "Toda la cuenta" and r["curva_visitas"][10]["valor"] == 60.0
    assert [p["visitas"] for p in r["puntos_visitas"]] == [200, 260]


def test_sin_anotaciones_no_hay_curvas_ni_hora_de_inicio():
    r = mon.armar_curvas([])
    assert r["curvas"] == {} and r["curva_visitas"] is None and r["anotaciones"] == 0 and r["desde"] is None and r["puntos_visitas"] == []


# ── Conversión ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_conversion_de_cada_anotacion_es_ordenes_netas_hasta_ese_momento_sobre_visitas_acumuladas():
    ordenes = [datetime(2030, 3, 5, 9, 40), datetime(2030, 3, 5, 10, 20), datetime(2030, 3, 5, 11, 10)]     # hora argentina de cada orden neta
    puntos = [{"momento": _t(10, 0).isoformat(), "visitas": 100}, {"momento": _t(11, 0).isoformat(), "visitas": 250}, {"momento": _t(12, 0).isoformat(), "visitas": 300}]
    r = mon.conversion_acumulada(puntos, ordenes)
    assert r == [{"hora": "10:00", "visitas": 100, "ordenes": 1, "conversion": 1.0},
                 {"hora": "11:00", "visitas": 250, "ordenes": 2, "conversion": 0.8},
                 {"hora": "12:00", "visitas": 300, "ordenes": 3, "conversion": 1.0}]
    assert mon.conversion_acumulada([{"momento": _t(9).isoformat(), "visitas": 0}], ordenes) == []          # sin visitas no hay conversión que mostrar


# ── Publicidad de hoy ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_resumen_de_publicidad_suma_la_cuenta_y_solo_lista_campanas_con_actividad():
    campanas = [
        {"id": 1, "nombre": "Negra", "estado": "active", "prints": 92753, "clicks": 331, "costo": 38216.54, "unidades": 4, "ventas_atribuidas": 218885.66},
        {"id": 2, "nombre": "Pausada", "estado": "paused", "prints": 0, "clicks": 0, "costo": 0, "unidades": 0, "ventas_atribuidas": 0},
        {"id": 3, "nombre": "Chica", "estado": "active", "prints": 1000, "clicks": 5, "costo": 500.0, "unidades": 0, "ventas_atribuidas": 0},
    ]
    r = mon.resumen_de_publicidad(campanas)
    assert (r["impresiones"], r["clics"], r["gasto"], r["unidades"]) == (93753, 336, 38716.54, 4) and r["ctr"] == 0.36 and r["ventas_atribuidas"] == 218885.66
    assert [c["id"] for c in r["campanas"]] == ["1", "3"]                                  # la que más gastó primero; la pausada sin nada no se lista
    assert mon.resumen_de_publicidad([])["ctr"] == 0.0


# ── Visitas de Mercado Libre ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, codigo, datos):
        self.status_code, self._datos, self.text = codigo, datos, json.dumps(datos)

    def json(self):
        return self._datos


def _visitas(monkeypatch, respuesta, hoy):
    monkeypatch.setattr(mon, "hoy_argentina", lambda: hoy)
    monkeypatch.setattr(mon.meli_http, "get", lambda *a, **k: respuesta)
    return mon.visitas_de_la_cuenta("tok", 99)


def test_las_visitas_de_hoy_y_ayer_salen_de_los_dias_que_informa_mercado_libre(monkeypatch):
    r = _Resp(200, {"results": [{"date": "2030-03-04T00:00:00Z", "total": 742}, {"date": "2030-03-05T00:00:00Z", "total": 535}]})
    assert _visitas(monkeypatch, r, date(2030, 3, 5)) == {"hoy": 535, "ayer": 742}


def test_si_mercado_libre_no_informa_el_dia_de_hoy_no_se_muestra_el_de_ayer_como_si_fuera_de_hoy(monkeypatch):
    r = _Resp(200, {"results": [{"date": "2030-03-03T00:00:00Z", "total": 100}, {"date": "2030-03-04T00:00:00Z", "total": 742}]})
    assert _visitas(monkeypatch, r, date(2030, 3, 5)) == {"hoy": None, "ayer": 742}


def test_un_error_de_mercado_libre_es_no_se_nunca_cero_visitas(monkeypatch):
    assert _visitas(monkeypatch, _Resp(500, {}), date(2030, 3, 5)) is None
    monkeypatch.setattr(mon.meli_http, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin red")))
    assert mon.visitas_de_la_cuenta("tok", 99) is None


# ── Ganancia por hora ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_ganancia_por_hora_suma_lo_que_dejo_cada_venta_en_su_hora():
    ventas = [{"momento": "2030-03-05T10:35", "raw": {"ganancia_neta": 1000.5}}, {"momento": "2030-03-05T10:59", "raw": {"ganancia_neta": -200.25}},
              {"momento": "2030-03-05T15:05", "raw": {"ganancia_neta": 3000}}, {"momento": None, "raw": {"ganancia_neta": 99999}}]
    r = mon.ganancia_por_hora(ventas)
    assert (r["por_hora"][10]["ganancia"], r["por_hora"][10]["ventas"]) == (800.25, 2) and r["por_hora"][15]["ganancia"] == 3000.0 and r["total"] == 3800.25


# ── Costo de publicidad por unidad vendida ───────────────────────────────────────────────────────────────────────────────────────────

def test_el_costo_por_unidad_es_gasto_sobre_unidades_y_sin_unidades_no_hay_costo():
    assert metricas.costo_por_unidad(1000, 5) == 200.0 and metricas.costo_por_unidad(1000, 3) == 333.33
    assert metricas.costo_por_unidad(1000, 0) is None and metricas.costo_por_unidad(0, 0) is None and metricas.costo_por_unidad(None, None) is None
    assert metricas.costo_por_unidad(0, 4) == 0.0                                          # unidades sin gasto: la publicidad no costó nada


def test_los_periodos_cuentan_hasta_hoy_incluido():
    hoy = date(2026, 10, 13)
    assert metricas.rango_de_dias(1, hoy) == ("2026-10-13", "2026-10-13")
    assert metricas.rango_de_dias(7, hoy) == ("2026-10-07", "2026-10-13") and metricas.rango_de_dias(30, hoy) == ("2026-09-14", "2026-10-13")
    assert metricas.PERIODOS_CPA == (1, 7, 14, 30)


def test_el_cpa_de_la_cuenta_usa_todas_las_unidades_netas_y_el_de_cada_campana_las_de_sus_productos():
    campanas = [
        {"id": 1, "nombre": "Camperas", "estado": "active", "costo": 600.0, "unidades": 3},
        {"id": 2, "nombre": "Medias", "estado": "active", "costo": 300.0, "unidades": 1},
        {"id": 3, "nombre": "Pausada", "estado": "paused", "costo": 0, "unidades": 0},               # sin gasto ni ventas: no se lista
        {"id": 4, "nombre": "Gasta y no vende", "estado": "active", "costo": 100.0, "unidades": 0},
    ]
    unidades = {"MLA-A": 4, "MLA-B": 1, "MLA-ORGANICA": 5}                                         # MLA-ORGANICA no está en ninguna campaña
    r = metricas.armar_cpa(7, "2030-03-01", "2030-03-07", 1000.0, campanas, unidades, {"MLA-A": "1", "MLA-B": "2", "MLA-X": "4"})
    assert r["disponible"] and r["gasto"] == 1000.0 and r["unidades_netas"] == 10 and r["cpa"] == 100.0           # 1000 ÷ las 10 unidades netas de TODA la cuenta
    por_id = {c["id"]: c for c in r["campanas"]}
    assert set(por_id) == {"1", "2", "4"}
    assert (por_id["1"]["unidades_netas"], por_id["1"]["cpa"], por_id["1"]["unidades_meli"]) == (4, 150.0, 3)       # 600 ÷ 4
    assert (por_id["2"]["unidades_netas"], por_id["2"]["cpa"]) == (1, 300.0)
    assert por_id["4"]["cpa"] is None and por_id["4"]["gasto"] == 100.0                                              # gastó y no vendió: sin costo por unidad, no un 0
    assert [c["id"] for c in r["campanas"]] == ["1", "2", "4"]                                                       # la que más gastó primero
    sin_ventas = metricas.armar_cpa(1, "2030-03-05", "2030-03-05", 500.0, [], {}, {})
    assert sin_ventas["cpa"] is None and sin_ventas["unidades_netas"] == 0


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma al salir: lo que escribe el código bajo prueba se revierte al final."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def _crear_tabla(cur):
    cur.execute(open(os.path.join(RAIZ, "migrations", "0048_monitor_snapshots.sql"), encoding="utf-8").read())


@pytest.mark.db
@CON_BASE
def test_calcular_cpa_real_con_la_base_y_mercado_libre_simulados(monkeypatch):
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-CPA-{os.getpid()}"
    monkeypatch.setattr(metricas, "hoy_argentina", lambda: date(2030, 3, 7))
    monkeypatch.setattr(ads, "obtener_advertiser_id", lambda *a, **k: 555)
    monkeypatch.setattr(ads, "obtener_campanas_con_metricas", lambda *a, **k: [{"id": 9, "nombre": "Camperas", "estado": "active", "costo": 600.0, "unidades": 2}])
    monkeypatch.setattr(ads, "obtener_gasto_ads_total_periodo", lambda *a, **k: 600.0)
    monkeypatch.setattr(ads, "obtener_anuncios_con_metricas", lambda *a, **k: {f"{p}-MLA1": {"costo": 600.0, "campana_id": "9"}})
    try:
        with db.conexion_usuario(usuario, cuenta) as conexion:
            monkeypatch.setattr(metricas.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            for orden, id_meli, unidades, dia in ((f"{p}-1", f"{p}-MLA1", 3, "2030-03-07"), (f"{p}-2", f"{p}-MLA2", 2, "2030-03-06"), (f"{p}-3", f"{p}-MLA1", 7, "2030-03-01")):
                cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen) VALUES (%s, %s, %s, '', 't', %s, 1000, %s, 'meli')",
                            (cuenta, orden, id_meli, unidades, dia))
            r7 = metricas.calcular_cpa_real(usuario, cuenta, "tok", 7)                           # del 1 al 7 de marzo: 3 + 2 + 7 = 12 unidades netas
            assert r7["disponible"] and r7["unidades_netas"] == 12 and r7["cpa"] == 50.0
            assert [(c["id"], c["unidades_netas"], c["cpa"]) for c in r7["campanas"]] == [("9", 10, 60.0)]          # MLA1 vendió 3 + 7
            r1 = metricas.calcular_cpa_real(usuario, cuenta, "tok", 1)                           # solo hoy: 3 unidades
            assert r1["unidades_netas"] == 3 and r1["cpa"] == 200.0
            assert metricas.cpa_por_publicacion(usuario, cuenta, "tok", 7) == {f"{p}-MLA1": {"gasto": 600.0, "unidades": 10, "cpa": 60.0}}
            monkeypatch.setattr(ads, "obtener_gasto_ads_total_periodo", lambda *a, **k: None)         # Mercado Libre no contestó: no se sabe, nunca un costo inventado
            assert metricas.calcular_cpa_real(usuario, cuenta, "tok", 14)["disponible"] is False
            monkeypatch.setattr(ads, "obtener_advertiser_id", lambda *a, **k: None)
            assert metricas.calcular_cpa_real(usuario, cuenta, "tok", 30)["disponible"] is False and metricas.cpa_por_publicacion(usuario, cuenta, "tok") is None
            raise _Revertir()
    except _Revertir:
        pass


# ── Anotaciones y pantalla, contra la base real ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.db
@CON_BASE
def test_las_ventas_por_hora_separan_netas_y_canceladas_contra_la_base_real():
    import db
    usuario, cuenta = _cuenta()
    p, dia = f"PRUEBA-HORA-{os.getpid()}", "2030-03-05"
    try:
        with db.conexion_usuario(usuario, cuenta) as conexion:
            cur = conexion.cursor()
            for orden, hora, cantidad, precio in ((f"{p}-1", "10:15:00", 2, 5000), (f"{p}-2", "10:45:00", 1, 3000), (f"{p}-3", "15:00:00", 1, 7000)):
                cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, hora_venta, hora_normalizada, origen) VALUES (%s, %s, %s, '', 't', %s, %s, %s, %s, true, 'meli')",
                            (cuenta, orden, f"{p}-MLA1", cantidad, precio, dia, hora))
            fila = {"id_orden": f"{p}-4", "id_meli": f"{p}-MLA1", "cantidad": 1, "precio_venta": 4000, "fecha_venta": dia, "hora_venta": "10:30:00", "hora_normalizada": True}
            cur.execute("INSERT INTO ventas_retiradas (cuenta_id, id_orden, motivo, monto, fila) VALUES (%s, %s, 'cancelada', 4000, %s::jsonb)", (cuenta, f"{p}-4", json.dumps(fila)))
            horas = mon.ventas_por_hora(cur, dia)
            assert len(horas) == 24
            assert horas[10]["netas"] == {"ordenes": 2, "unidades": 3, "facturado": 13000.0} and horas[10]["canceladas"] == {"ordenes": 1, "unidades": 1, "facturado": 4000.0}
            assert horas[15]["netas"]["facturado"] == 7000.0 and horas[15]["canceladas"]["ordenes"] == 0 and horas[3]["netas"]["ordenes"] == 0
            assert [m.hour for m in mon.momentos_de_ordenes_netas(cur, dia)] == [10, 10, 15]
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_el_flujo_completo_de_anotaciones_curvas_y_conversion_contra_la_base_real(monkeypatch):
    import db
    usuario, cuenta = _cuenta()
    p, dia = f"PRUEBA-MON-{os.getpid()}", "2030-03-05"
    campanas = lambda impresiones, clics, costo, unidades: [{"id": 9, "nombre": "Camperas", "estado": "active", "prints": impresiones, "clicks": clics, "costo": costo, "unidades": unidades, "ventas_atribuidas": unidades * 50000.0}]
    try:
        with db.conexion_admin() as conexion:                  # crear la tabla (DDL) lo puede hacer solo el administrador; todo se revierte al final
            monkeypatch.setattr(mon.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            _crear_tabla(cur)
            for orden, hora in ((f"{p}-1", "15:10:00"), (f"{p}-2", "16:20:00")):
                cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, hora_venta, hora_normalizada, origen) VALUES (%s, %s, %s, '', 't', 1, 50000, %s, %s, true, 'meli')",
                            (cuenta, orden, f"{p}-MLA1", dia, hora))
            # dos anotaciones previas (15:00 y 15:30) y una vieja (de hace 5 días) que la próxima anotación borra
            assert mon.guardar_anotacion(usuario, cuenta, campanas(1000, 10, 100.0, 0), 200, ahora=_t(15, 0, dia=1)) == 2
            assert mon.guardar_anotacion(usuario, cuenta, campanas(1000, 10, 100.0, 0), 200, ahora=_t(15, 0)) == 2
            assert mon.guardar_anotacion(usuario, cuenta, campanas(1600, 16, 160.0, 1), 260, ahora=_t(15, 30)) == 2
            assert mon.guardar_anotacion(usuario, cuenta, [{"id": 8, "prints": 0, "clicks": 0, "costo": 0, "unidades": 0}], None) == 0       # sin actividad ni visitas no se guarda nada
            cur.execute("SELECT COUNT(*) FROM monitor_snapshots WHERE cuenta_id = %s AND momento < %s", (cuenta, _t(0, 0, dia=3)))
            assert cur.fetchone()[0] == 0                                                         # la de hace 5 días ya se borró
            assert len(mon.leer_anotaciones(usuario, cuenta, dia)) == 4

            # La pantalla: Mercado Libre informa 1.900 impresiones y 330 visitas a las 15:45; la última anotación es de las 15:30 (15 min): anota de nuevo
            monkeypatch.setattr(mon, "medir_ahora", lambda *a, **k: {"campanas": campanas(1900, 19, 190.0, 1), "visitas": {"hoy": 330, "ayer": 700}, "con_publicidad": True})
            r = mon.datos_de_medicion(usuario, cuenta, "tok", ahora=_t(15, 45))
            assert r["tabla"] and r["con_publicidad"] and r["anotaciones"] == 3 and r["medido_desde"] == "15:00" and r["actualizado"] == "15:45:00"
            imp = r["publicidad"]["curvas"]["*"]["impresiones"]
            assert imp[15]["valor"] == 900.0 and imp[15]["cubierta"] == 0.75                      # 600 de 15:00 a 15:30 y 300 de 15:30 a 15:45
            assert r["publicidad"]["curvas"]["9"]["unidades"][15]["valor"] == 1.0 and r["publicidad"]["gasto"] == 190.0 and r["publicidad"]["impresiones"] == 1900
            assert r["visitas"]["hoy"] == 330 and r["visitas"]["ayer"] == 700 and r["visitas"]["curva"][15]["valor"] == 130.0
            assert r["visitas"]["ordenes_netas"] == 2 and r["visitas"]["conversion_actual"] == 0.61                  # 2 ÷ 330
            assert [(c["hora"], c["ordenes"], c["visitas"]) for c in r["visitas"]["conversion"]] == [("15:00", 0, 200), ("15:30", 1, 260), ("15:45", 1, 330)]
            raise _Revertir()
    except _Revertir:
        pass


def test_si_la_tabla_de_anotaciones_todavia_no_existe_todo_sigue_funcionando(monkeypatch):
    import psycopg

    class _SinTabla:
        def __enter__(self):
            raise psycopg.errors.UndefinedTable("no existe monitor_snapshots")

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(mon.db, "conexion_usuario", lambda u, c=None: _SinTabla())
    assert mon.leer_anotaciones(1, 7, "2030-03-05") is None and mon._ultima_anotacion(1, 7) is None
    assert mon.guardar_anotacion(1, 7, [{"id": 1, "prints": 5, "clicks": 1, "costo": 1.0, "unidades": 0}], 10) == 0
    assert mon.armar_curvas([])["curvas"] == {}


@pytest.mark.db
@CON_BASE
def test_las_pantallas_y_endpoints_del_monitor_responden(monkeypatch):
    import app as a
    usuario, cuenta = _cuenta()
    monkeypatch.setattr(a.token_manager, "asegurar_token_valido", lambda cuenta_id: "token-simulado")
    pedidos = []

    def cpa_falso(usuario_id, cuenta_id, access_token, dias):
        pedidos.append(dias)
        return {"dias": dias, "disponible": False, "campanas": []}
    monkeypatch.setattr(a.metricas_mod, "calcular_cpa_real", cpa_falso)
    cliente = a.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario, cuenta
    html = cliente.get("/monitor_en_vivo").get_data(as_text=True)
    assert 'id="mon-g-ingresos"' in html and "Monitor en vivo" in html and 'href="#icon-pulse"' in html
    ventas = cliente.get("/api/monitor/ventas").get_json()
    assert set(ventas) >= {"fecha", "brutas", "canceladas", "netas", "frase", "por_hora"} and len(ventas["por_hora"]) == 24
    assert ventas["brutas"]["facturado"] == round(ventas["netas"]["facturado"] + ventas["canceladas"]["facturado"], 2)
    assert cliente.get("/api/monitor/cpa?dias=3").get_json()["dias"] == 1                                       # un período que no existe cae en «hoy»
    assert cliente.get("/api/monitor/cpa?dias=30").get_json()["dias"] == 30 and pedidos == [1, 30]


def test_la_migracion_de_las_anotaciones_aisla_por_cuenta_activa_y_no_deja_modificar():
    """La tabla nueva tiene que tener la política con `app.cuenta_actual` (las de otra cuenta del mismo usuario no se ven) y solo SELECT/INSERT/DELETE para la app."""
    sql = open(os.path.join(RAIZ, "migrations", "0048_monitor_snapshots.sql"), encoding="utf-8").read()
    assert "ENABLE ROW LEVEL SECURITY" in sql and "app.cuenta_actual" in sql and "app.usuario_actual" in sql
    assert "GRANT SELECT, INSERT, DELETE ON monitor_snapshots TO app_backend" in sql and "UPDATE ON monitor_snapshots" not in sql

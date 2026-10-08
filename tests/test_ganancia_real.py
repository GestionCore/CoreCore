"""
Red de seguridad de la FÓRMULA CENTRAL del producto (metricas.calcular_ganancia_real):
    Ganancia Neta Real = Facturación − Cargos MeLi − Envíos − Publicidad − Costo de fabricación − cargos mensuales de Mercado Libre.
Hasta el 2026-10-08 no tenía ninguna prueba directa (16 % de cobertura en metricas.py): solo la tocaba el recorrido de pantallas, que verifica que no se caiga, no que dé bien.
Acá la base se reemplaza por un cursor que devuelve filas conocidas y Mercado Libre por respuestas fijas, y los números esperados están calculados A MANO (en los comentarios).
Si una consulta nueva aparece en la función y no está simulada, la prueba falla a propósito: hay que decidir qué devuelve.
"""
from datetime import date, datetime

import pytest

import ads
import db
import facturacion
import metricas

DESDE, HASTA = "2026-09-01", "2026-09-30"


class _Cursor:
    """Un cursor de mentira que contesta según qué tabla se consulta (las filas llegan como diccionarios, igual que con row_factory=dict_row)."""

    def __init__(self, datos):
        self.datos, self.ultimo = datos, None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "SUM(precio_venta * cantidad)" in s:
            self.ultimo = ("uno", self.datos["periodo_anterior"])
        elif "FROM ventas WHERE fecha_venta BETWEEN" in s and "id_orden, id_meli, titulo" in s:
            self.ultimo = ("todos", self.datos["ventas"])
        elif "FROM productos_variantes" in s:
            self.ultimo = ("todos", self.datos["variantes"])
        elif "FROM productos_padre" in s:
            self.ultimo = ("todos", self.datos["productos"])
        elif "FROM incidencias_posventa" in s:
            self.ultimo = ("todos", self.datos["incidencias"])
        elif "FROM ventas_retiradas" in s:
            self.ultimo = ("uno", self.datos["retiradas"])
        else:
            raise AssertionError(f"consulta sin simular en calcular_ganancia_real: {s[:120]}")

    def fetchall(self):
        return self.ultimo[1]

    def fetchone(self):
        return self.ultimo[1]


class _Conexion:
    def __init__(self, datos):
        self.datos = datos

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, **kw):
        return _Cursor(self.datos)


def _venta(id_orden, id_meli, titulo, cantidad, precio, cargo, envio, **extra):
    base = {"id_orden": id_orden, "id_meli": id_meli, "titulo": titulo, "cantidad": cantidad, "precio_venta": precio, "cargo_venta": cargo, "costo_envio": envio,
            "fecha_venta": date(2026, 9, 10), "id_variante": f"v-{id_orden}", "envio_estado": "entregado", "costo_flex": 0, "retenciones": None, "neto_recibido": None,
            "financiacion": 0, "cuotas": 1, "momento": datetime(2026, 9, 10, 14, 35)}
    base.update(extra)
    return base


def _datos():
    """Cuatro ventas de tres publicaciones; ver los números esperados en cada prueba."""
    return {
        "periodo_anterior": {"facturado": 50000, "unidades": 5, "ordenes": 4},
        "ventas": [
            # MLA1 (campera): 2 unidades a 10.000, comisión 2.000, envío 1.500, retenciones 300; MeLi depositó 16.200 = 20.000 − 2.000 − 1.500 − 300 (cuadra justo)
            _venta("o1", "MLA1", "Campera Negra", 2, 10000, 2000, 1500, retenciones=300, neto_recibido=16200, financiacion=400),
            # MLA1: 1 unidad a 10.000, comisión 1.000, envío 700, retenciones 150; debía depositar 8.150 y depositó 8.100 (−50)
            _venta("o2", "MLA1", "Campera Negra", 1, 10000, 1000, 700, retenciones=150, neto_recibido=8100, financiacion=200),
            # MLA2 (sin costo de fabricación cargado): 3 unidades a 5.000, comisión 2.250; envío FLEX: 900 que cobra la logística propia (MeLi no cobra envío), depositó 12.750
            _venta("o3", "MLA2", "Termo Acero", 3, 5000, 2250, 900, costo_flex=900, retenciones=0, neto_recibido=12750),
            # MLA3: 1 unidad a 20.000, comisión 3.000, envío 2.000; todavía sin pago informado (neto_recibido None)
            _venta("o4", "MLA3", "Mochila Grande", 1, 20000, 3000, 2000, envio_estado="pendiente"),
        ],
        "variantes": [{"id_variante": "v-o1", "talle": "M", "color": "Negro"}, {"id_variante": "v-o2", "talle": "L", "color": "Único"}],
        "productos": [
            {"id_meli": "MLA1", "precio_costo": 4000, "thumbnail": "t1.jpg", "listing_type_id": "gold_special"},
            {"id_meli": "MLA2", "precio_costo": None, "thumbnail": None, "listing_type_id": "gold_pro"},
            {"id_meli": "MLA3", "precio_costo": 8000, "thumbnail": "t3.jpg", "listing_type_id": "gold_special"},
        ],
        "incidencias": [
            {"tipo": "claim", "motivo": "No llegó", "estado": "opened", "id_orden": "o1", "fecha": date(2026, 9, 12), "monto_retenido": 5000, "afecta_reputacion": "affected"},
            {"tipo": "mediation", "motivo": "Arrepentimiento", "estado": "opened", "id_orden": "o2", "fecha": date(2026, 9, 13), "monto_retenido": 0, "afecta_reputacion": "not_affected"},
            {"tipo": "returns", "motivo": "No le quedó", "estado": "closed", "id_orden": "o3", "fecha": date(2026, 9, 14), "monto_retenido": 0, "afecta_reputacion": None},
            {"tipo": "cancelled", "motivo": None, "estado": "closed", "id_orden": "o9", "fecha": date(2026, 9, 15), "monto_retenido": 0, "afecta_reputacion": None},
            {"tipo": "claim", "motivo": "Producto distinto", "estado": "opened", "id_orden": "o4", "fecha": date(2026, 9, 16), "monto_retenido": 0, "afecta_reputacion": None},
        ],
        "retiradas": {"ordenes": 2, "monto": 12345},
    }


@pytest.fixture
def calcular(monkeypatch):
    """Devuelve una función que corre calcular_ganancia_real con la base y Mercado Libre simulados (se pueden cambiar los datos y las respuestas de Ads y de la factura)."""
    def _calcular(datos=None, advertiser="A1", costos_ads=None, gasto_ads=2000.0, fijos=1234.5, falla_ads=False, falla_fijos=False):
        datos = datos if datos is not None else _datos()
        monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _Conexion(datos))
        monkeypatch.setattr(ads, "obtener_advertiser_id", lambda token, cuenta_id: advertiser)
        costos = {"MLA1": 900.0, "MLA3": 500.0} if costos_ads is None else costos_ads

        def _costos(token, adv, d, h, ids):
            if falla_ads:
                raise RuntimeError("Ads no responde")
            return costos
        monkeypatch.setattr(ads, "obtener_costos_ads_por_item", _costos)
        monkeypatch.setattr(ads, "obtener_gasto_ads_total_periodo", lambda *a, **k: gasto_ads)

        def _fijos(*a, **k):
            if falla_fijos:
                raise RuntimeError("la factura no responde")
            return {"total": fijos, "items": [], "completo": True}
        monkeypatch.setattr(facturacion, "cargos_fuera_de_ventas", _fijos)
        return metricas.calcular_ganancia_real(1, 1, "token", DESDE, HASTA)
    return _calcular


# ── La fórmula, venta por venta ─────────────────────────────────────────────────────────────────────────────────────────────

def test_cada_venta_es_facturacion_menos_comision_envio_publicidad_y_costo_de_fabricacion(calcular):
    r = calcular()
    por_orden = {v["id_orden"]: v["raw"] for v in r["ventas"]}
    # Publicidad por unidad = total de la publicación ÷ unidades vendidas: MLA1 900 ÷ 3 = 300 por unidad; MLA3 500 ÷ 1.
    # o1: 20.000 − 2.000 − 1.500 − 600 (2×300) − 8.000 (2×4.000) = 7.900
    assert por_orden["o1"] == {"precio_venta": 20000.0, "cargo_venta": 2000.0, "costo_envio": 1500.0, "costo_ads": 600.0, "costo_fabricacion": 8000.0, "ganancia_neta": 7900.0}
    # o2: 10.000 − 1.000 − 700 − 300 − 4.000 = 4.000
    assert por_orden["o2"]["ganancia_neta"] == 4000.0 and por_orden["o2"]["costo_ads"] == 300.0
    # o3: sin costo de fabricación cargado cuenta 0 (NO rompe): 15.000 − 2.250 − 900 − 0 − 0 = 11.850
    assert por_orden["o3"]["ganancia_neta"] == 11850.0 and por_orden["o3"]["costo_fabricacion"] == 0.0 and por_orden["o3"]["costo_ads"] == 0.0
    # o4: 20.000 − 3.000 − 2.000 − 500 − 8.000 = 6.500
    assert por_orden["o4"]["ganancia_neta"] == 6500.0


def test_el_resumen_suma_las_ventas_y_descuenta_los_cargos_mensuales_de_mercado_libre(calcular):
    raw = calcular()["resumen"]["raw"]
    assert raw["facturado"] == 65000.0                                   # 20.000 + 10.000 + 15.000 + 20.000
    assert raw["comision"] == 8250.0                                     # 2.000 + 1.000 + 2.250 + 3.000
    assert raw["envios"] == 5100.0                                       # 1.500 + 700 + 900 + 2.000
    assert raw["costo_ads"] == 1400.0                                    # 600 + 300 + 0 + 500
    assert raw["costo_fabricacion"] == 20000.0                           # 8.000 + 4.000 + 0 + 8.000
    assert raw["ganancia_neta_ventas"] == 30250.0                        # 7.900 + 4.000 + 11.850 + 6.500 = lo que dejó cada venta
    assert raw["cargos_fuera_de_ventas"] == 1234.5                       # eShop, almacenamiento, etc. que no están en ninguna venta
    assert raw["ganancia_neta"] == 29015.5                               # la REAL: 30.250 − 1.234,5
    # Facturación − comisión − envíos − publicidad − costo − cargos mensuales: la regla de negocio escrita tal cual
    assert raw["ganancia_neta"] == round(raw["facturado"] - raw["comision"] - raw["envios"] - raw["costo_ads"] - raw["costo_fabricacion"] - raw["cargos_fuera_de_ventas"], 2)


def test_las_retenciones_se_muestran_aparte_y_no_restan_de_la_ganancia(calcular):
    raw = calcular()["resumen"]["raw"]
    assert raw["retenciones"] == 450.0                                   # 300 + 150 + 0 + (None cuenta 0): pago anticipado de impuestos, NO un gasto
    assert raw["ganancia_neta_ventas"] == 30250.0                        # y no están descontadas: el mismo número de arriba


def test_la_ganancia_negativa_se_marca(calcular):
    datos = _datos()
    datos["productos"][0]["precio_costo"] = 9000                         # costo alto: cada unidad de MLA1 pierde plata (o1: 20.000 − 2.000 − 1.500 − 600 − 18.000 = −2.100; o2: −1.000)
    r = calcular(datos)
    assert r["resumen"]["ganancia_neta_negativa"] is False               # el total sigue positivo gracias a las otras ventas (11.850 + 6.500 − 3.100 − 1.234,5 = 14.015,5)…
    assert r["resumen"]["raw"]["ganancia_neta"] == 14015.5
    assert [v["es_negativo"] for v in r["ventas"]][:2] == [True, True]   # …pero esas dos ventas se marcan como pérdida
    datos["productos"][1]["precio_costo"] = 99999                        # y con un costo imposible en TODAS las demás, el total también es pérdida
    datos["productos"][2]["precio_costo"] = 99999
    assert calcular(datos)["resumen"]["ganancia_neta_negativa"] is True


# ── Conciliación contra lo que Mercado Libre depositó de verdad ─────────────────────────────────────────────────────────────

def test_la_conciliacion_compara_lo_esperado_con_lo_depositado_sin_contar_el_envio_flex(calcular):
    c = calcular()["resumen"]["raw"]["conciliacion"]
    assert c["ventas"] == 3 and c["cobertura_pct"] == 75                 # 3 de 4 ventas ya tienen el pago informado
    assert c["facturado"] == 45000.0
    # esperado = (20.000−2.000−1.500−300) + (10.000−1.000−700−150) + (15.000−2.250−(900−900 de Flex)−0) = 16.200 + 8.150 + 12.750 = 37.100; depositado = 16.200 + 8.100 + 12.750 = 37.050
    assert c["esperado"] == 37100.0 and c["depositado"] == 37050.0 and c["diferencia"] == -50.0
    assert c["coincide_pct"] == 99.9                                     # 100 − 50 ÷ 37.050


def test_sin_ventas_todo_es_cero_y_no_hay_division_por_cero(calcular):
    datos = _datos()
    datos["ventas"] = []
    datos["incidencias"] = []
    r = calcular(datos, costos_ads={}, fijos=0.0)
    raw = r["resumen"]["raw"]
    assert raw["facturado"] == 0.0 and raw["ganancia_neta"] == 0.0 and r["ventas"] == [] and r["consolidados"] == []
    assert raw["conciliacion"]["cobertura_pct"] == 0 and raw["conciliacion"]["coincide_pct"] is None
    assert r["posventa"]["financiacion"] is None


# ── Consolidado por modelo: promedio PONDERADO real, nunca promedio simple ──────────────────────────────────────────────────

def test_el_consolidado_por_modelo_es_total_sobre_unidades_y_cierra_con_las_ventas(calcular):
    r = calcular()
    campera = next(c for c in r["consolidados"] if c["titulo"] == "Campera Negra")
    # MLA1: 3 unidades, facturó 30.000, comisión 3.000, envío 2.200, publicidad 900, costo 12.000
    assert campera["unidades"] == 3 and campera["raw"]["total_facturado"] == 30000.0
    assert campera["raw"]["precio_promedio"] == 10000.0
    assert campera["raw"]["neto_u"] == pytest.approx(3966.67, abs=0.01)           # 10.000 − 1.000 − 733,33 − 300 − 4.000
    assert campera["raw"]["neto_total"] == pytest.approx(11900.0, abs=0.01)       # = 7.900 + 4.000: el consolidado cierra con la suma de sus ventas
    assert sum(c["raw"]["neto_total"] for c in r["consolidados"]) == pytest.approx(r["resumen"]["raw"]["ganancia_neta_ventas"], abs=0.05)


def test_dos_talles_con_distinto_precio_dan_el_promedio_ponderado_y_no_el_simple():
    filas = metricas.consolidar_por_modelo({
        "MLA10": {"titulo": "Campera Jean Talle M", "thumbnail": None, "unidades": 1, "facturado": 10000.0, "costo_fab": 0.0, "cargos_meli": 0.0, "envios": 0.0, "ads": 0.0},
        "MLA11": {"titulo": "Campera Jean Talle L", "thumbnail": None, "unidades": 9, "facturado": 90000.0 * 0.5, "costo_fab": 0.0, "cargos_meli": 0.0, "envios": 0.0, "ads": 0.0},
    })
    assert len(filas) == 1                                                       # los talles son publicaciones de un mismo modelo
    assert filas[0]["unidades"] == 10 and filas[0]["raw"]["precio_promedio"] == 5500.0      # (10.000 + 45.000) ÷ 10; el promedio simple (10.000 + 5.000) ÷ 2 daría 7.500
    assert len(filas[0]["variantes"]) == 2


def test_un_modelo_sin_unidades_no_divide_por_cero():
    fila = metricas._fila_consolidada({"titulo": "X", "thumbnail": None, "unidades": 0, "facturado": 0.0, "cargos_meli": 0.0, "envios": 0.0, "ads": 0.0, "costo_fab": 0.0})
    assert fila["raw"]["precio_promedio"] == 0.0 and fila["raw"]["neto_total"] == 0.0


# ── Cuando Mercado Libre falla, la pantalla sigue con lo que tiene ──────────────────────────────────────────────────────────

def test_sin_cuenta_de_publicidad_no_hay_costo_de_ads_ni_se_rompe(calcular):
    r = calcular(advertiser=None)
    assert r["ads_disponible"] is False and r["resumen"]["raw"]["costo_ads"] == 0.0
    assert r["resumen"]["raw"]["ganancia_neta_ventas"] == 30250.0 + 1400.0           # sin publicidad descontada: 31.650


def test_si_falla_publicidad_no_se_dice_que_esta_disponible_con_cero(calcular):
    """Antes `ads_disponible` pasaba a True ANTES de pedir los costos: si fallaban, la pantalla mostraba «publicidad: $0» en lugar de «no disponible»."""
    r = calcular(falla_ads=True)
    assert r["ads_disponible"] is False and r["resumen"]["raw"]["costo_ads"] == 0.0 and r["gasto_ads_total_periodo"] is None


def test_si_algunas_publicaciones_no_pudieron_leerse_se_informa_cuantas(calcular):
    """Mercado Libre no contestó el costo de publicidad de 2 publicaciones: cuentan sin gasto (la ganancia podría estar sobrestimada) y la pantalla tiene que poder avisarlo."""
    costos = ads.CostosAds({"MLA1": 900.0})
    costos.incompleto = 2
    r = calcular(costos_ads=costos)
    assert r["ads_disponible"] is True and r["ads_incompleto"] == 2
    assert calcular()["ads_incompleto"] == 0                              # con la lectura completa no hay aviso


def test_si_falla_la_factura_se_sigue_sin_los_cargos_mensuales_y_se_avisa(calcular):
    r = calcular(falla_fijos=True)
    assert r["resumen"]["raw"]["cargos_fuera_de_ventas"] == 0.0 and r["cargos_fuera_de_ventas"]["completo"] is False
    assert r["resumen"]["raw"]["ganancia_neta"] == 30250.0


# ── Lo que acompaña a la plata: financiación, reclamos y comparación ───────────────────────────────────────────────────────

def test_el_costo_de_ofrecer_cuotas_es_un_desglose_y_no_resta_otra_vez(calcular):
    r = calcular()
    f = r["posventa"]["financiacion"]
    assert f["total_raw"] == 600.0 and f["pct_facturado"] == 0.9                        # 400 + 200 sobre 65.000
    assert f["publicaciones"][0]["id_meli"] == "MLA1" and f["publicaciones"][0]["pct"] == 2.0 and f["sin_cargo"] == 2
    assert r["resumen"]["raw"]["ganancia_neta"] == 29015.5                              # ya está dentro de los cargos de MeLi: la ganancia no cambia


def test_solo_cuentan_como_reclamo_los_que_afectan_la_reputacion_o_no_se_sabe(calcular):
    p = calcular()["posventa"]
    assert p["reclamos"] == 2                      # el «affected» y el que todavía no se consultó (NULL se trata como «podría afectar»)
    assert p["reclamos_sin_impacto"] == 1          # la mediación que MeLi marcó «not_affected»
    assert p["devoluciones"] == 1 and p["cancelaciones"] == 1
    assert p["dinero_retenido_monto"] == 5000.0
    assert p["ranking_motivos_devolucion"] == [{"motivo": "No le quedó", "cantidad": 1}]
    assert p["ventas_retiradas"] == 2
    sin_impacto = [i for i in p["lista"] if i["sin_impacto"]]
    assert len(sin_impacto) == 1 and sin_impacto[0]["tipo"] == "RECLAMO"


def test_la_comparacion_con_el_periodo_anterior_usa_el_mismo_largo_de_dias(calcular):
    c = calcular()["comparacion_anterior"]
    assert (c["desde"], c["hasta"]) == ("2026-08-02", "2026-08-31")       # septiembre tiene 30 días: los 30 inmediatamente anteriores
    assert c["facturado_raw"] == 50000.0 and c["variacion_facturado_pct"] == 30.0     # (65.000 − 50.000) ÷ 50.000
    assert metricas._obtener_comparacion_periodo_anterior(_Cursor(_datos()), "2026-09-10", "2026-09-10")["desde"] == "2026-09-09"      # un día: el día de antes


def test_la_hora_de_la_venta_sale_en_formato_argentino(calcular):
    assert calcular()["ventas"][0]["momento"] == "2026-09-10T14:35"
    assert calcular()["ventas"][0]["fecha"] == "2026-09-10"


def test_el_talle_y_el_color_salen_de_la_variante(calcular):
    ventas = {v["id_orden"]: v["talle"] for v in calcular()["ventas"]}
    assert ventas["o1"] == "M / Negro" and ventas["o2"] == "L" and ventas["o3"] == "Único"      # sin color real solo el talle; sin variante «Único»

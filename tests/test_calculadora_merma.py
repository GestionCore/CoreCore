"""
Calculadora «Unit Economics» (calculadora_costos.py): lo que deja UNA venta con devoluciones, embalaje y publicidad (lote de 100 ventas), la escala Flex del vendedor para el
envío de vuelta y los datos reales de un producto. Números hechos a mano; lo que toca la base corre contra la base real dentro de una transacción que se revierte.
"""
import os
from datetime import date

import pytest

import calculadora_costos as cc

CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


# ── La cuenta de una venta con mermas ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_14_devoluciones_cada_100_se_reparten_entre_las_86_ventas_concretadas():
    r = cc.simular_merma(precio=25000, comision=3500, costo_fabricacion=8000, costo_envio=3000, costo_ads=500, costo_embalaje=200, tasa_devolucion=14, costo_envio_devolucion=7000)
    assert (r["base"], r["devoluciones"], r["concretadas"]) == (100, 14.0, 86.0)
    assert r["hundido_total"] == 468000.0                                          # 100 × (500 + 200 + 3.000) + 14 × 7.000 = 370.000 + 98.000
    assert r["hundido_por_venta"] == 5441.86                                       # 468.000 ÷ 86
    assert r["costo_total_por_venta"] == 16941.86 and r["ganancia_por_venta"] == 8058.14          # 3.500 + 8.000 + 5.441,86 = 16.941,86; 25.000 − eso
    assert r["margen_pct"] == 32.2
    assert r["por_venta"] == {"comision": 3500.0, "fabricacion": 8000.0, "envio": 3488.37, "ads": 581.4, "embalaje": 232.56, "devoluciones": 1139.53}
    assert round(sum(r["por_venta"].values()), 1) == round(r["costo_total_por_venta"], 1)
    assert r["ganancia_sin_devoluciones"] == 9800.0 and r["costo_de_las_devoluciones"] == 1741.86            # sin devoluciones: 25.000 − 3.500 − 8.000 − 3.000 − 500 − 200
    assert r["frase"] == "Tuviste que pagar 100 envíos/ads para concretar 86 ventas. Absorbiendo esa pérdida, vender 1 sola unidad te cuesta realmente $16.942 y te deja $8.058 limpios."


def test_sin_devoluciones_la_cuenta_es_la_de_una_venta_sola_y_no_hay_nada_que_absorber():
    r = cc.simular_merma(25000, 3500, 8000, 3000, 500, 200, 0, 7000)
    assert r["concretadas"] == 100.0 and r["devoluciones"] == 0.0 and r["frase"] is None
    assert r["ganancia_por_venta"] == 9800.0 == r["ganancia_sin_devoluciones"] and r["costo_de_las_devoluciones"] == 0.0       # el envío de vuelta no se cobra si nadie devuelve
    assert cc.simular_merma(1000, 100)["ganancia_por_venta"] == 900.0                  # solo precio y comisión: el resto vale 0


def test_una_tasa_con_decimales_da_ventas_concretadas_con_decimales_y_la_frase_lo_dice():
    r = cc.simular_merma(10000, 1000, 0, 0, 0, 0, 12.5, 0)
    assert r["concretadas"] == 87.5 and r["devoluciones"] == 12.5 and "para concretar 87,5 ventas" in r["frase"]


def test_si_la_cuenta_da_perdida_la_frase_lo_dice_en_vez_de_inventar_una_ganancia():
    r = cc.simular_merma(10000, 1500, 7000, 2500, 1000, 0, 20, 5000)                   # hundido: 100 × (1.000 + 2.500) + 20 × 5.000 = 450.000 ÷ 80 = 5.625; 10.000 − 1.500 − 7.000 − 5.625 = −4.125
    assert r["ganancia_por_venta"] == -4125.0 and "te hace perder $4.125" in r["frase"] and "limpios" not in r["frase"]


def test_datos_imposibles_no_rompen_nada():
    assert cc.simular_merma(0, 100) == {"error": "Falta el precio de venta."} and "error" in cc.simular_merma(None, None)
    assert "100 %" in cc.simular_merma(10000, 1000, tasa_devolucion=100)["error"] and "error" in cc.simular_merma(10000, 1000, tasa_devolucion=250)
    r = cc.simular_merma("25000", "abc", "", None, "nan", "inf", "-5", -300)           # texto, vacíos, NaN, infinito y negativos valen 0
    assert r["ganancia_por_venta"] == 25000.0 and r["concretadas"] == 100.0


# ── La escala Flex del vendedor ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_escala_flex_promedia_el_rango_de_los_precios_cargados():
    umbrales = [{"id": 1, "resto": True, "precio": 10000, "zonas": []}, {"id": 2, "precio": 4000, "zonas": ["CABA"]}, {"id": 3, "precio": "6500", "zonas": ["Lanus"]}, {"id": 4, "precio": None, "zonas": []}]
    assert cc.escala_flex(umbrales) == {"minimo": 4000.0, "maximo": 10000.0, "promedio": 7000.0}            # si paga entre $4.000 y $10.000, se asume $7.000
    assert cc.escala_flex([{"precio": 3000}]) == {"minimo": 3000.0, "maximo": 3000.0, "promedio": 3000.0}
    assert cc.escala_flex([{"resto": True, "precio": None}, {"precio": 0}, {"precio": "abc"}]) is None and cc.escala_flex([]) is None and cc.escala_flex(None) is None


# ── Lo que CoreLux ya sabe del producto ──────────────────────────────────────────────────────────────────────────────────────────────

def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


@pytest.mark.db
@CON_BASE
def test_los_datos_reales_del_producto_salen_de_sus_ventas_de_90_dias():
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-CALC-{os.getpid()}"
    try:
        with db.conexion_usuario(usuario, cuenta) as conexion:
            cur = conexion.cursor()
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, precio_costo, category_id, listing_type_id) VALUES (%s, %s, 'Buzo de prueba', 25000, 8000, 'MLA109096', 'gold_pro')", (cuenta, f"{p}-A"))
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio) VALUES (%s, %s, 'Sin ventas', 100)", (cuenta, f"{p}-B"))
            for orden, cantidad, precio, cargo, envio, retenciones, dia in ((f"{p}-1", 2, 10000, 2800, 1200, 300, "2030-03-05"), (f"{p}-2", 1, 12000, 3000, 900, None, "2030-03-06"), (f"{p}-3", 9, 10000, 99999, 99999, 99999, "2029-01-01")):
                cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, cargo_venta, costo_envio, retenciones, fecha_venta, origen) VALUES (%s, %s, %s, '', 't', %s, %s, %s, %s, %s, %s, 'meli')",
                            (cuenta, orden, f"{p}-A", cantidad, precio, cargo, envio, retenciones, dia))
            d = cc.datos_de_producto(cur, cuenta, f"{p}-A", hoy=date(2030, 3, 10))
            assert (d["titulo"], d["precio"], d["costo_fabricacion"], d["category_id"], d["listing_type_id"]) == ("Buzo de prueba", 25000.0, 8000.0, "MLA109096", "gold_pro")
            r = d["reales"]                                                                          # la venta de 2029 queda fuera de los 90 días
            assert (r["unidades"], r["dias"], r["pocas_ventas"]) == (3, 90, False)
            assert r["comision_pct"] == 18.1 and r["comision_unitaria"] == 1933.33                    # (2.800 + 3.000) ÷ 32.000 y ÷ 3 unidades
            assert r["envio_unitario"] == 700.0                                                       # (1.200 + 900) ÷ 3
            assert r["retenciones_pct"] == 1.5                                                        # 300 ÷ 20.000: solo cuenta la venta que informó retenciones
            assert d["flex"] is None or set(d["flex"]) == {"minimo", "maximo", "promedio"}
            sin = cc.datos_de_producto(cur, cuenta, f"{p}-B", hoy=date(2030, 3, 10))
            assert sin["reales"] is None and sin["costo_fabricacion"] is None and sin["precio"] == 100.0
            assert cc.datos_de_producto(cur, cuenta, f"{p}-NO-EXISTE") is None
            raise _Revertir()
    except _Revertir:
        pass


# ── Endpoints ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.db
@CON_BASE
def test_los_endpoints_de_la_calculadora(monkeypatch):
    import app as a
    import db
    usuario, cuenta = _cuenta()
    with db.conexion_usuario(usuario, cuenta) as conexion:
        cur = conexion.cursor()
        cur.execute("SELECT id_meli FROM productos_padre WHERE cuenta_id = %s ORDER BY id LIMIT 1", (cuenta,))
        id_meli = cur.fetchone()[0]
    monkeypatch.setattr(a.token_manager, "asegurar_token_valido", lambda cuenta_id: "token-simulado")
    monkeypatch.setattr(a.calculadora_costos, "caminos_de_categorias", lambda ids, headers=None: {i: "Ropa › Camperas" for i in ids})
    cliente = a.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario, cuenta

    html = cliente.get("/calculadora").get_data(as_text=True)
    assert 'id="calc-ads"' in html and 'id="calc-tasa"' in html and "Costo unitario de Ads" in html and 'id="calc-btn-escala"' in html

    m = cliente.get("/api/calculadora_merma?precio=25000&comision=3500&costo_fabricacion=8000&costo_envio=3000&costo_ads=500&costo_embalaje=200&tasa_devolucion=14&costo_envio_devolucion=7000").get_json()
    assert m["ganancia_por_venta"] == 8058.14 and m["concretadas"] == 86.0 and "100 envíos/ads para concretar 86 ventas" in m["frase"]
    assert "error" in cliente.get("/api/calculadora_merma?precio=0").get_json()

    assert set((cliente.get("/api/calculadora_flex").get_json())) == {"escala"}

    assert cliente.get("/api/calculadora_producto").status_code == 400 and cliente.get("/api/calculadora_producto?id_meli=NO-EXISTE-123").status_code == 404
    monkeypatch.setattr(a.metricas_mod, "cpa_por_publicacion", lambda u, c, t, dias=30: {id_meli: {"gasto": 6000.0, "unidades": 4, "cpa": 1500.0}})
    d = cliente.get(f"/api/calculadora_producto?id_meli={id_meli}").get_json()
    assert d["id_meli"] == id_meli and d["ads"] == {"disponible": True, "dias": 30, "gasto": 6000.0, "unidades": 4, "cpa": 1500.0}
    monkeypatch.setattr(a.metricas_mod, "cpa_por_publicacion", lambda u, c, t, dias=30: {})                          # no está en Product Ads: no gastó
    assert cliente.get(f"/api/calculadora_producto?id_meli={id_meli}").get_json()["ads"] == {"disponible": True, "dias": 30, "gasto": 0.0, "unidades": 0, "cpa": None}
    monkeypatch.setattr(a.metricas_mod, "cpa_por_publicacion", lambda u, c, t, dias=30: None)                         # Mercado Libre no contestó: no se sabe, no «cero»
    assert cliente.get(f"/api/calculadora_producto?id_meli={id_meli}").get_json()["ads"] == {"disponible": False}

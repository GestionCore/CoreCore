"""
Ola 3 (T13): el costo de una VARIANTE también cuenta en Precios, Promociones, la calculadora, el margen del Dashboard, el capital en Stock y los datos del asistente.
Antes esas pantallas leían solo el costo de la publicación: con costos distintos por variante (una remera cuesta distinto según el color) mostraban un margen que no era.
La regla es la de la Ganancia Real: cada variante pesa lo que vendió, y una variante sin costo propio usa el de su publicación. Números hechos a mano.
"""
import os
from datetime import date

import pytest

import catalogo
import costos_moneda as cm
import precios
from tests.conftest import CursorFalso
from tests.test_costos_moneda import CON_BASE, _Revertir, _cuenta, _padre, _variante


# ── La cuenta de una publicación: promedio de lo que se vendió ───────────────────────────────────────────────────────────────────────

def test_cada_variante_pesa_lo_que_vendio_y_una_sin_costo_propio_usa_el_de_la_publicacion():
    # costo de la publicación 4.000; la variante A tiene 6.000 propio y vendió 3; la B no tiene propio (usa 4.000) y vendió 1: (3 × 6.000 + 1 × 4.000) ÷ 4 = 5.500
    r = cm.resumir_costo_de_publicacion(4000, [(6000, 3), (None, 1)])
    assert r["costo"] == 5500.0 and r["minimo"] == 4000.0 and r["maximo"] == 6000.0 and r["distintos"] and r["con_ventas"] and r["unidades_sin_costo"] == 0


def test_sin_ventas_es_el_promedio_simple_y_con_todas_iguales_no_hay_nada_que_avisar():
    r = cm.resumir_costo_de_publicacion(0, [(6000, 0), (4000, 0)])
    assert r["costo"] == 5000.0 and not r["con_ventas"] and r["distintos"]
    iguales = cm.resumir_costo_de_publicacion(0, [(5000, 2), (5000, 1)])
    assert iguales["costo"] == 5000.0 and not iguales["distintos"]


def test_una_variante_sin_ningun_costo_no_entra_en_el_promedio_y_se_cuentan_sus_unidades():
    # la publicación no tiene costo: la variante A (6.000, 3 u.) sí; la B no tiene ninguno y vendió 2: no se le inventa un costo
    r = cm.resumir_costo_de_publicacion(0, [(6000, 3), (None, 2)])
    assert r["costo"] == 6000.0 and r["unidades_sin_costo"] == 2
    assert cm.resumir_costo_de_publicacion(0, [(None, 5), (None, 1)]) is None                  # ninguna tiene costo: sigue siendo «sin costo»


def test_el_costo_de_una_publicacion_sin_variantes_con_costo_es_el_suyo():
    assert cm.costo_de_publicacion({}, "MLA1", 4000) == 4000.0 and cm.costo_de_publicacion({}, "MLA1", None) == 0.0
    assert cm.costo_de_publicacion({"MLA1": {"costo": 5500.0}}, "MLA1", 4000) == 5500.0


def test_sin_cuenta_no_se_consulta_nada():
    assert cm.costos_efectivos(CursorFalso(), None) == {}


# ── Contra la base real: la unión con las ventas (incluida la publicación sin variaciones, «<id>_unica») ─────────────────────────────

@pytest.mark.db
@CON_BASE
def test_el_costo_efectivo_sale_de_las_ventas_de_cada_variante_en_la_base_real():
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-EFE-{os.getpid()}"
    hoy = date(2030, 3, 20)
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            # Con dos variantes: A (6.000 propio) vendió 3, B (sin propio → usa los 4.000 de la publicación) vendió 1; una venta vieja (fuera de los 90 días) no cuenta
            id_padre = _padre(cur, cuenta, f"{p}-A", costo=4000)
            _variante(cur, cuenta, id_padre, f"{p}-A-V1", costo=6000)
            _variante(cur, cuenta, id_padre, f"{p}-A-V2")
            # Sin variaciones: su variante se llama «<id>_unica» y sus ventas guardan id_variante vacío
            id_unica = _padre(cur, cuenta, f"{p}-B", costo=0)
            _variante(cur, cuenta, id_unica, f"{p}-B_unica", costo=7000)
            # Una publicación sin ningún costo por variante: no aparece (usa el suyo)
            id_normal = _padre(cur, cuenta, f"{p}-C", costo=3000)
            _variante(cur, cuenta, id_normal, f"{p}-C_unica")

            def venta(orden, id_meli, id_variante, cantidad, dia):
                cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen) VALUES (%s, %s, %s, %s, 't', %s, 20000, %s, 'meli')",
                            (cuenta, orden, id_meli, id_variante, cantidad, dia))
            venta(f"{p}-o1", f"{p}-A", f"{p}-A-V1", 3, date(2030, 3, 10))
            venta(f"{p}-o2", f"{p}-A", f"{p}-A-V2", 1, date(2030, 3, 11))
            venta(f"{p}-o3", f"{p}-A", f"{p}-A-V1", 50, date(2029, 1, 1))
            venta(f"{p}-o4", f"{p}-B", "", 2, date(2030, 3, 12))
            efectivos = cm.costos_efectivos(cur, cuenta, hoy=hoy)
            assert efectivos[f"{p}-A"]["costo"] == 5500.0 and efectivos[f"{p}-A"]["distintos"]          # (3 × 6.000 + 1 × 4.000) ÷ 4
            assert efectivos[f"{p}-B"]["costo"] == 7000.0 and not efectivos[f"{p}-B"]["distintos"]      # la venta con id_variante vacío encuentra «_unica»
            assert f"{p}-C" not in efectivos
            solo = cm.costos_efectivos(cur, cuenta, hoy=hoy, id_meli=f"{p}-A")
            assert list(solo) == [f"{p}-A"]                                                              # el filtro por publicación trae solo esa
            raise _Revertir()
    except _Revertir:
        pass


# ── Precios ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _precios(variantes, costo_publicacion=0, unidades=4, ingreso=80000, cargos=16000, envios=4000):
    ventas = [("MLA1", unidades, ingreso, cargos, envios)] if unidades else []
    productos = [("MLA1", "Remera", None, None, 20000, costo_publicacion)]
    filas_variantes = [("MLA1", costo_publicacion, f"V{i}", propio, u) for i, (propio, u) in enumerate(variantes)]
    return precios.obtener_datos(CursorFalso(ventas, productos, filas_variantes), 1, 20.0, 0.0)


def test_precios_usa_el_promedio_de_las_variantes_en_vez_de_dejar_la_publicacion_sin_costo():
    d = _precios([(6000, 3), (4000, 1)])
    assert d["sin_costo"] == [] and len(d["items"]) == 1
    i = d["items"][0]
    assert i["costo"] == 5500.0                                          # promedio de lo vendido
    assert i["minimo"] == 8130                                           # (5.500 + 1.000 de envío) ÷ (1 − 20 % de comisión) = 8.125, redondeado a $10 hacia arriba
    assert i["costo_variantes"] == {"minimo": 4000.0, "maximo": 6000.0, "distintos": True, "con_ventas": True, "unidades_sin_costo": 0}


def test_precios_avisa_cuando_vendio_variantes_sin_costo_cargado():
    i = _precios([(6000, 3), (None, 2)], unidades=5, ingreso=100000, cargos=20000, envios=5000)["items"][0]
    assert i["costo"] == 6000.0 and i["costo_variantes"]["unidades_sin_costo"] == 2 and not i["costo_variantes"]["distintos"]


def test_precios_sin_costos_por_variante_calcula_exactamente_como_siempre():
    i = _precios([], costo_publicacion=5000)["items"][0]
    assert i["costo"] == 5000.0 and i["costo_variantes"] is None


def test_la_publicacion_sin_ningun_costo_sigue_en_sin_costo():
    d = _precios([(None, 2), (None, 2)])
    assert d["items"] == [] and len(d["sin_costo"]) == 1


def test_el_ajuste_de_una_publicacion_sin_ventas_se_juzga_contra_su_variante_mas_cara():
    d = _precios([(6000, 0), (4000, 0)], unidades=0)
    (sin_ventas,) = d["sin_ventas"]
    assert sin_ventas["costo"] == 5000.0 and sin_ventas["costo_variantes"]["maximo"] == 6000.0
    # bajar el precio 70 % → $6.000, igual al costo de la variante cara: no deja ganancia (con el promedio de $5.000 no se habría avisado)
    por_id = {a["id_meli"]: a for a in precios.calcular_ajuste(d, -70)}
    assert por_id["MLA1"]["estado"] == "pierde" and "variantes" in por_id["MLA1"]["motivo"]
    ok = {a["id_meli"]: a for a in precios.calcular_ajuste(d, -50)}                 # $10.000: sobre la variante más cara
    assert ok["MLA1"]["estado"] == "ok"


# ── Stock: el capital a costo, cada variante con SU costo ────────────────────────────────────────────────────────────────────────────

class _Conexion:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        filas = self.filas

        class _Cursor:
            actual = []

            def execute(self, sql, params=None):
                self.actual = filas if "variantes_deduplicadas" in sql else []

            def fetchall(self):
                return self.actual
        return _Cursor()


def _fila(id_meli, propio, full, etiqueta, costo, estado="active", titulo="Remera Lisa"):
    return (id_meli, titulo, 10000, estado, None, None, None, None, None, propio, full, "Único", etiqueta, costo)


def _stats(monkeypatch, filas):
    monkeypatch.setattr(catalogo.db, "conexion_usuario", lambda u, c=None: _Conexion(filas))
    return catalogo.obtener_productos_y_estadisticas(1, 1)[1]


def test_el_capital_en_stock_a_costo_usa_el_costo_de_cada_variante(monkeypatch):
    # azul: 3 propias + 0 FULL a $100; rojo: 1 propia + 1 FULL a $200; verde: 4 propias SIN costo (no se inventa uno)
    s = _stats(monkeypatch, [_fila("MLA1", 3, 0, "Azul", 100), _fila("MLA1", 1, 1, "Rojo", 200), _fila("MLA1", 4, 0, "Verde", 0)])
    assert s["capital_costo"] == "700"                                # 3 × 100 + 2 × 200
    assert s["unidades_con_costo"] == 5 and s["unidades_sin_costo"] == 4
    assert s["valor_total"] == "90.000"                               # lo de siempre: a precio de venta (9 unidades × $10.000)


def test_las_pausadas_no_cuentan_en_el_capital(monkeypatch):
    s = _stats(monkeypatch, [_fila("MLA1", 3, 0, "Azul", 100), _fila("MLA2", 9, 0, "Azul", 100, estado="paused", titulo="Buzo Viejo")])
    assert s["unidades_con_costo"] == 3 and s["capital_costo"] == "300"                         # el modelo pausado no está a la venta: no cuenta


def test_la_misma_variante_publicada_dos_veces_no_suma_dos_veces_el_capital(monkeypatch):
    s = _stats(monkeypatch, [_fila("MLA1", 3, 0, "Azul", 100), _fila("MLA2", 5, 0, "Azul", 100)])             # la misma variante en dos publicaciones: se queda con el mayor stock
    assert s["unidades_con_costo"] == 5 and s["capital_costo"] == "500"


# ── Que las demás pantallas lean el costo efectivo ───────────────────────────────────────────────────────────────────────────────────

def _fuente(nombre):
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), nombre), encoding="utf-8").read()


def test_promociones_la_calculadora_y_el_margen_del_dashboard_usan_el_costo_efectivo():
    assert "costos_moneda.costo_de_publicacion(efectivos, r[0], r[3])" in _fuente("app.py")
    assert "costos_moneda.costos_efectivos(cursor, cuenta_id, VENTANA_REALES_DIAS, hoy, id_meli)" in _fuente("calculadora_costos.py")
    assert "costos_moneda.costo_de_publicacion(efectivos, id_meli, costo)" in _fuente("dashboard.py")


def test_la_plantilla_de_promociones_avisa_que_el_costo_cambia_segun_la_variante():
    html = _fuente(os.path.join("templates", "promociones.html"))
    assert "data-costo-min" in html and "data-costo-max" in html and "El costo cambia según la variante" in html


# ── La pantalla de Precios explica de dónde sale el costo ────────────────────────────────────────────────────────────────────────────

def _render_precios(datos):
    import app as aplicacion
    with aplicacion.app.test_request_context("/precios"):
        return aplicacion.render_template("precios.html", active_nav="precios", **datos)


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")
def test_precios_explica_que_el_costo_cambia_segun_la_variante_y_cual_usa():
    html = _render_precios(_precios([(6000, 3), (4000, 1)]))
    assert "El costo cambia según la variante" in html and "4.000" in html and "6.000" in html and "5.500" in html and "el promedio de lo que vendiste" in html


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")
def test_precios_avisa_las_unidades_vendidas_de_variantes_sin_costo_y_no_dice_nada_si_no_hay_diferencias():
    html = _render_precios(_precios([(6000, 3), (None, 2)], unidades=5, ingreso=100000, cargos=20000, envios=5000))
    assert "2 unidades vendidas de variantes sin costo cargado" in html and "El costo cambia según la variante" not in html
    assert "costo cambia" not in _render_precios(_precios([], costo_publicacion=5000))

"""
Controles de los datos reales de cada cuenta (controles_de_datos.py, /admin/salud). `evaluar` es puro: se prueba con números hechos a mano en los bordes de cada umbral. `reunir` corre contra la
base real (solo lectura y una transacción que se revierte) para probar que cada consulta es válida y que un error como el de las ventas sin variante se DETECTA.
"""
import os

import pytest

import controles_de_datos as cd

CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


def _sano(**cambios):
    v = {"ventas": 500, "sin_variante": 0, "sin_publicacion": 0, "viejas": 400, "viejas_sin_pago": 4, "conciliacion_ventas": 300, "conciliacion_depositado": 1_000_000.0,
         "conciliacion_esperado": 998_000.0, "envios_pendientes": 0, "activas": 20, "activas_sin_variantes": 0, "activas_sin_categoria": 0, "activas_sin_precio": 0,
         "activas_sin_costo": 0, "horas_sin_normalizar": 0, "stock_negativo": 0}
    v.update(cambios)
    return v


def _claves(v):
    return {h["clave"]: h for h in cd.evaluar(v)}


def test_una_cuenta_sana_no_tiene_hallazgos():
    assert cd.evaluar(_sano()) == []


def test_las_ventas_que_no_encuentran_su_variante_son_una_falla_pasado_el_diez_por_ciento():
    assert "sin_variante" not in _claves(_sano(sin_variante=50))                                 # justo 10 %: todavía no
    h = _claves(_sano(sin_variante=51))["sin_variante"]
    assert h["tono"] == "danger" and "51 de 500" in h["titulo"] and "10,2 %" in h["titulo"]
    assert _claves(_sano(sin_variante=500))["sin_variante"]["tono"] == "danger"                  # el caso real de antes del arreglo: casi todas


def test_las_ventas_de_publicaciones_que_ya_no_estan_solo_avisan():
    assert _claves(_sano(sin_publicacion=51))["sin_publicacion"]["tono"] == "warn"
    assert "sin_publicacion" not in _claves(_sano(sin_publicacion=50))


def test_los_pagos_sin_informar_se_miden_sobre_las_ventas_viejas():
    assert "sin_pago" not in _claves(_sano(viejas=400, viejas_sin_pago=60))                      # 15 % justo
    assert _claves(_sano(viejas=400, viejas_sin_pago=61))["sin_pago"]["tono"] == "warn"
    assert "sin_pago" not in _claves(_sano(viejas=0, viejas_sin_pago=0))                         # sin ventas viejas no hay nada que medir


def test_la_conciliacion_avisa_desde_2_por_ciento_y_falla_desde_5_en_cualquier_sentido():
    assert "conciliacion" not in _claves(_sano(conciliacion_depositado=1_019_000.0, conciliacion_esperado=1_000_000.0))        # +1,9 %
    assert _claves(_sano(conciliacion_depositado=1_020_000.0, conciliacion_esperado=1_000_000.0))["conciliacion"]["tono"] == "warn"
    h = _claves(_sano(conciliacion_depositado=930_000.0, conciliacion_esperado=1_000_000.0))["conciliacion"]
    assert h["tono"] == "danger" and "menos plata" in h["titulo"] and "7" in h["titulo"]                                       # −7 %: depositaron menos de lo esperado
    assert "más plata" in _claves(_sano(conciliacion_depositado=1_100_000.0, conciliacion_esperado=1_000_000.0))["conciliacion"]["titulo"]


def test_con_pocas_ventas_no_se_concilia():
    assert "conciliacion" not in _claves(_sano(conciliacion_ventas=29, conciliacion_depositado=10.0, conciliacion_esperado=1000.0))
    assert "conciliacion" not in _claves(_sano(conciliacion_esperado=0))                         # sin base no hay porcentaje


def test_lo_roto_del_catalogo_y_del_stock_es_una_falla():
    claves = _claves(_sano(activas_sin_variantes=2, stock_negativo=1, envios_pendientes=3, horas_sin_normalizar=4, activas_sin_categoria=1, activas_sin_precio=1))
    assert claves["activas_sin_variantes"]["tono"] == "danger" and claves["stock_negativo"]["tono"] == "danger"
    assert claves["envios_pendientes"]["tono"] == "warn" and claves["horas"]["tono"] == "warn" and "2 publicaciones activas sin categoría o sin precio" in claves["activas_incompletas"]["titulo"]


def test_las_publicaciones_sin_costo_se_avisan_como_lo_que_mas_infla_la_ganancia():
    h = _claves(_sano(activas=71, activas_sin_costo=17))["sin_costo"]
    assert h["tono"] == "warn" and "17 de 71" in h["titulo"]
    assert "sin_costo" not in _claves(_sano(activas=0, activas_sin_costo=0))


@CON_BASE
def test_cada_control_corre_con_la_base_real_y_devuelve_los_numeros_esperados():
    import db
    with db.conexion_admin() as conexion:
        cur = conexion.cursor()
        cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
        cuenta = cur.fetchone()[0]
        v = cd.reunir(cur, cuenta)
    esperadas = {"ventas", "sin_variante", "sin_publicacion", "viejas", "viejas_sin_pago", "conciliacion_ventas", "conciliacion_depositado", "conciliacion_esperado", "envios_pendientes",
                 "activas", "activas_sin_variantes", "activas_sin_categoria", "activas_sin_precio", "activas_sin_costo", "horas_sin_normalizar", "stock_negativo"}
    assert set(v) == esperadas
    assert all(isinstance(x, (int, float)) or hasattr(x, "quantize") for x in v.values())
    cd.evaluar({k: float(x) if hasattr(x, "quantize") else x for k, x in v.items()})             # y evaluar no se rompe con datos reales


class _Revertir(Exception):
    pass


@CON_BASE
def test_el_error_de_las_ventas_sin_variante_se_detecta_con_datos_reales():
    """Se arma el caso que pasó de verdad (ventas cuya variante no existe): el control las cuenta; al crearse la variante «<id>_unica» dejan de contarse. El umbral se prueba aparte, con números a mano."""
    import db
    pid = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            antes = cd.reunir(cur, cuenta)
            id_meli = f"PRUEBA-CTL-{pid}"
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado) VALUES (%s, %s, 'Prueba controles', 1000, 'active') RETURNING id", (cuenta, id_meli))
            id_padre = cur.fetchone()[0]
            for i in range(25):
                cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen)
                               VALUES (%s, %s, %s, '', 't', 1, 100, current_date, 'meli')""", (cuenta, f"{id_meli}-{i}", id_meli))
            roto = cd.reunir(cur, cuenta)
            assert roto["sin_variante"] - antes["sin_variante"] == 25 and roto["ventas"] - antes["ventas"] == 25
            assert "sin_variante" in {h["clave"] for h in cd.evaluar({**roto, "ventas": 100, "sin_variante": 25 + 20})}          # 45 % de 100: rojo
            cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, stock_propio, stock_full) VALUES (%s, %s, %s, 1, 0)", (cuenta, f"{id_meli}_unica", id_padre))
            arreglado = cd.reunir(cur, cuenta)
            assert arreglado["sin_variante"] == antes["sin_variante"]                              # al existir «<id>_unica» esas ventas la encuentran
            raise _Revertir()
    except _Revertir:
        pass

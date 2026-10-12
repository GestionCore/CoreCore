"""
Costo de entrega Flex (flex.py): umbrales por zona, neto de reintegro (10 %), reparto entre los ítems de un pack y que `costo_envio` (lo que cuenta Ganancia Real) se corrija por diferencia: nunca dos veces.
Lógica pura con cursor simulado y el flujo completo contra la base real dentro de una transacción que se revierte. Números calculados a mano.
"""
import json
import os

import pytest

import flex


class _Revertir(Exception):
    pass


# ── Neto, etiquetas y configuración ─────────────────────────────────────────────────────────────────────────────────────────

def test_el_costo_neto_descuenta_el_reintegro_de_mercado_libre():
    assert flex.neto(2000) == 1800.0 and flex.neto("1234.5") == 1111.05 and flex.neto(0) == 0.0 and flex.neto(None) is None
    assert flex.REINTEGRO_MELI == 0.10


def test_etiquetas_de_los_umbrales():
    nombres = {"Lanus": "Lanús", "CABA": "CABA"}
    assert flex.etiqueta({"nombre": "Zona norte"}, nombres) == "Zona norte"
    assert flex.etiqueta({"resto": True}, nombres) == "Resto de las zonas"
    assert flex.etiqueta({"zonas": ["Lanus"]}, nombres) == "Lanús"
    assert flex.etiqueta({"zonas": ["Lanus", "CABA", "Quilmes"]}, nombres) == "CABA +2"            # la primera por orden alfabético y cuántas más
    assert flex.etiqueta({"zonas": []}, nombres) == "Umbral sin zonas"


class _CursorConfig:
    def __init__(self, fila):
        self.fila, self.escrituras = fila, []

    def execute(self, sql, params=None):
        if sql.lstrip().startswith(("UPDATE", "INSERT")):
            self.escrituras.append((sql, params))

    def fetchone(self):
        return self.fila


def test_la_configuracion_siempre_trae_el_umbral_resto_primero():
    assert flex.obtener_config(_CursorConfig(None), 7) == {"umbrales": [flex._umbral_resto()], "info": None}
    sin_resto = [{"id": 5, "zonas": ["CABA"], "precio": 1000}, {"id": 3, "zonas": ["Lanus"], "precio": 1500}]
    cfg = flex.obtener_config(_CursorConfig((sin_resto, {"zonas": []})), 7)
    assert [u["id"] for u in cfg["umbrales"]] == [1, 3, 5] and cfg["umbrales"][0]["resto"] is True and cfg["info"] == {"zonas": []}
    con_resto = [{"id": 4, "zonas": ["CABA"], "precio": 1000}, {"id": 2, "resto": True, "precio": 3000, "zonas": []}]
    assert [u["id"] for u in flex.obtener_config(_CursorConfig((con_resto, None)), 7)["umbrales"]] == [2, 4]       # el resto va primero aunque tenga otro id
    assert flex.obtener_config(_CursorConfig(("no es una lista", "tampoco")), 7)["info"] is None                  # datos corruptos: se ignoran


def test_el_umbral_de_una_zona_es_el_que_la_cubre_y_si_no_el_resto():
    umbrales = [{"id": 1, "resto": True, "precio": 3000, "zonas": []}, {"id": 2, "precio": 2000, "zonas": ["CABA"]}, {"id": 3, "precio": 2500, "zonas": ["La_Matanza_1", "La_Matanza_2"]}]
    assert flex.umbral_de_familia(umbrales, "caba")["id"] == 2
    assert flex.umbral_de_familia(umbrales, "la matanza")["id"] == 3                  # las dos zonas del partido son la misma familia
    assert flex.umbral_de_familia(umbrales, "lanus")["id"] == 1 and flex.umbral_de_familia(umbrales, None)["id"] == 1


# ── Guardar los umbrales: se valida todo antes de escribir ─────────────────────────────────────────────────────────────────

def _guardar(umbrales, info=None):
    cursor = _CursorConfig(([], info))
    ok, error = flex.guardar_umbrales(cursor, 7, umbrales)
    return ok, error, cursor.escrituras


RESTO = {"id": None, "resto": True, "precio": "3000"}


def test_guarda_umbrales_validos_asignando_ids_nuevos_y_limpiando_los_datos():
    ok, error, escrituras = _guardar([RESTO, {"id": None, "nombre": "  Zona sur muy larga " + "x" * 60, "precio": "1500,5", "zonas": ["Lanus", 5, "Quilmes"]}])
    assert (ok, error) == (True, None)
    guardado = json.loads(escrituras[0][1][0])
    assert [u["id"] for u in guardado] == [2, 3]                                                  # ids nuevos desde el siguiente al mayor usado (el 1 queda reservado para el resto)
    assert guardado[0]["precio"] == 3000.0 and guardado[0]["resto"] is True and guardado[0]["zonas"] == []
    assert guardado[1]["precio"] == 1500.5 and guardado[1]["zonas"] == ["Lanus", "Quilmes"] and len(guardado[1]["nombre"]) == 40


def test_conserva_los_ids_existentes_y_no_repite_ninguno():
    ok, _, escrituras = _guardar([{"id": 1, "resto": True, "precio": 3000}, {"id": 4, "precio": 1000, "zonas": ["CABA"]}, {"id": 4, "precio": 1200, "zonas": ["Lanus"]}])
    assert ok and [u["id"] for u in json.loads(escrituras[0][1][0])] == [1, 4, 5]                 # el segundo «4» repetido recibe uno nuevo


def test_el_resto_no_lleva_zonas_y_un_precio_vacio_es_sin_precio_cargado():
    ok, _, escrituras = _guardar([{"id": 1, "resto": True, "precio": "  ", "zonas": ["CABA"]}])
    assert ok and json.loads(escrituras[0][1][0])[0] == {"id": 1, "nombre": None, "precio": None, "zonas": [], "resto": True}


@pytest.mark.parametrize("umbrales, mensaje", [
    ("no es una lista", "hasta 8 umbrales"),
    ([dict(RESTO)] * 9, "hasta 8 umbrales"),
    (["texto"], "Umbral inválido"),
    ([{"resto": True, "precio": "abc"}], "no es un número válido"),
    ([{"resto": True, "precio": -1}], "entre $0 y $10.000.000"),
    ([{"resto": True, "precio": 10_000_000}], "entre $0 y $10.000.000"),
    ([{"precio": 1000, "zonas": ["CABA"]}], "umbral para el resto"),                                   # falta el resto
    ([{"resto": True, "precio": 1}, {"resto": True, "precio": 2}], "umbral para el resto"),            # dos restos
    ([{"resto": True}, {"precio": 1, "zonas": ["CABA"]}, {"precio": 2, "zonas": ["CABA"]}], "está en dos umbrales"),
])
def test_rechaza_lo_invalido_sin_escribir_nada(umbrales, mensaje):
    ok, error, escrituras = _guardar(umbrales)
    assert ok is False and mensaje in error and escrituras == []


def test_si_ya_sincronizo_las_zonas_rechaza_las_que_mercado_libre_no_cubre():
    info = {"zonas": [{"id": "CABA", "nombre": "CABA"}]}
    ok, error, escrituras = _guardar([{"resto": True}, {"precio": 1, "zonas": ["Lanus"]}], info=info)
    assert ok is False and "no está en tu cobertura" in error and escrituras == []
    assert _guardar([{"resto": True}, {"precio": 1, "zonas": ["CABA"]}], info=info)[0] is True


# ── Contra la base real: asignar costos a órdenes Flex ─────────────────────────────────────────────────────────────────────

def _venta(cur, cuenta, orden, id_meli, precio, cantidad=1, tipo="self_service", origen="meli", provincia="Capital Federal", localidad="Palermo", envio=0, flex_zona=None):
    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, cantidad, precio_venta, fecha_venta, origen, tipo_logistica, provincia, localidad, costo_envio, costo_flex, flex_zona)
                   VALUES (%s, %s, %s, %s, %s, '2026-09-10', %s, %s, %s, %s, %s, 0, %s)""", (cuenta, orden, id_meli, cantidad, precio, origen, tipo, provincia, localidad, envio, flex_zona))


def _fila(cur, cuenta, orden, id_meli):
    cur.execute("SELECT flex_zona, flex_zona_meli, costo_flex, costo_envio FROM ventas WHERE cuenta_id = %s AND id_orden = %s AND id_meli = %s", (cuenta, orden, id_meli))
    z, zm, cf, ce = cur.fetchone()
    return z, zm, float(cf), float(ce)


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_el_flujo_completo_de_costo_flex_contra_la_base_real():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario, cuenta = cur.fetchone()
    p = f"PRUEBA-FLEX-{os.getpid()}"
    umbrales = [{"id": 1, "nombre": None, "precio": 3000, "zonas": [], "resto": True}, {"id": 2, "nombre": "CABA", "precio": 2000, "zonas": ["CABA"], "resto": False}]
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(umbrales), cuenta))
            _venta(cur, cuenta, f"{p}-A", "MLA-A1", 10000, envio=100)                                   # un pack de CABA: dos ítems, 10.000 y 30.000
            _venta(cur, cuenta, f"{p}-A", "MLA-A2", 30000, envio=400)
            _venta(cur, cuenta, f"{p}-B", "MLA-B1", 8000, provincia="Buenos Aires", localidad="Lanús")   # otro partido: cae en el resto
            _venta(cur, cuenta, f"{p}-C", "MLA-C1", 5000, provincia="Córdoba", localidad="Córdoba")       # no se puede ubicar: resto
            _venta(cur, cuenta, f"{p}-D", "MLA-D1", 5000, tipo="drop_off")                                # Correo: no es Flex
            _venta(cur, cuenta, f"{p}-E", "MLA-E1", 5000, origen="manual")                                # venta manual: no se toca
            _venta(cur, cuenta, f"{p}-F", "MLA-F1", 5000, flex_zona=0)                                    # elegida «sin costo»: no se toca

            previa = flex.vista_previa(cur, cuenta)
            propias = {f["id"]: f for f in previa["umbrales"]}
            assert previa["sin_precio"] == 0 and propias[2]["costo"] >= 1800 and propias[1]["ordenes"] >= 2        # (la cuenta puede tener otras órdenes Flex reales pendientes: se mide lo mínimo propio)

            resueltas = flex.aplicar_automatico(cur, cuenta)
            assert resueltas >= 3
            # Pack de CABA: neto 2.000 × 0,9 = 1.800, repartido 1.800 × 10.000/40.000 = 450 y 1.800 × 30.000/40.000 = 1.350; costo_envio = lo que informó MeLi + el costo Flex
            assert _fila(cur, cuenta, f"{p}-A", "MLA-A1") == (2, "caba", 450.0, 550.0)
            assert _fila(cur, cuenta, f"{p}-A", "MLA-A2") == (2, "caba", 1350.0, 1750.0)
            assert _fila(cur, cuenta, f"{p}-B", "MLA-B1") == (1, "lanus", 2700.0, 2700.0)                   # resto: 3.000 × 0,9
            assert _fila(cur, cuenta, f"{p}-C", "MLA-C1")[:3] == (1, "", 2700.0)                              # sin familia: también el resto
            assert _fila(cur, cuenta, f"{p}-D", "MLA-D1") == (None, None, 0.0, 0.0)
            assert _fila(cur, cuenta, f"{p}-E", "MLA-E1") == (None, None, 0.0, 0.0)
            assert _fila(cur, cuenta, f"{p}-F", "MLA-F1") == (0, None, 0.0, 0.0)

            flex.aplicar_automatico(cur, cuenta)                                                              # repetirlo no cambia nada (ya no quedan pendientes)
            assert _fila(cur, cuenta, f"{p}-A", "MLA-A2") == (2, "caba", 1350.0, 1750.0)

            # El precio del resto sube a 4.000 y se pide recalcular las ya valuadas: 4.000 × 0,9 = 3.600; el envío se corrige por la DIFERENCIA (no 2.700 + 3.600)
            umbrales[0]["precio"] = 4000
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(umbrales), cuenta))
            flex.aplicar_automatico(cur, cuenta, incluir_valuadas=True)
            assert _fila(cur, cuenta, f"{p}-B", "MLA-B1")[2:] == (3600.0, 3600.0)
            assert _fila(cur, cuenta, f"{p}-A", "MLA-A1") == (2, "caba", 450.0, 550.0)                       # el umbral de CABA no cambió
            assert _fila(cur, cuenta, f"{p}-F", "MLA-F1") == (0, None, 0.0, 0.0)                              # «sin costo» sigue sin costo

            # A mano: la orden C pasa a CABA y queda marcada; recalcular NO la pisa
            assert flex.asignar_manual(cur, cuenta, f"{p}-C", 2) == (True, None)
            assert _fila(cur, cuenta, f"{p}-C", "MLA-C1") == (2, "*manual", 1800.0, 1800.0)
            umbrales[0]["precio"] = 5000
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(umbrales), cuenta))
            flex.aplicar_automatico(cur, cuenta, incluir_valuadas=True)
            assert _fila(cur, cuenta, f"{p}-C", "MLA-C1") == (2, "*manual", 1800.0, 1800.0)
            assert flex.asignar_manual(cur, cuenta, f"{p}-C", flex.ZONA_SIN_COSTO) == (True, None)
            assert _fila(cur, cuenta, f"{p}-C", "MLA-C1") == (0, "*manual", 0.0, 0.0)                         # «sin costo»: el envío vuelve a lo que informó MeLi (0)

            # Errores al elegir a mano
            assert flex.asignar_manual(cur, cuenta, f"{p}-D", 2) == (False, "Esa venta no es de Flex.")
            assert flex.asignar_manual(cur, cuenta, f"{p}-NO-EXISTE", 2) == (False, "No encontré esa venta.")
            assert flex.asignar_manual(cur, cuenta, f"{p}-B", 99) == (False, "Ese umbral no existe.")
            umbrales[1]["precio"] = None
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(umbrales), cuenta))
            assert flex.asignar_manual(cur, cuenta, f"{p}-B", 2) == (False, "Cargá primero el precio de ese umbral en Costos.")

            r = flex.resumen_periodo(cur, cuenta, "2026-09-10", "2026-09-10")
            assert r["ordenes"] >= 4 and r["costo"] >= 450 + 1350 + 3600
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_un_umbral_sin_precio_no_valua_y_se_cuenta_aparte():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario, cuenta = cur.fetchone()
    p = f"PRUEBA-FLEX2-{os.getpid()}"
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps([{"id": 1, "nombre": None, "precio": None, "zonas": [], "resto": True}]), cuenta))
            _venta(cur, cuenta, f"{p}-A", "MLA-A1", 10000)
            antes = flex.contar_pendientes(cur, cuenta)
            previa = flex.vista_previa(cur, cuenta)
            assert previa["sin_precio"] >= 1 and previa["ordenes"] == 0 and previa["costo_total"] == 0
            assert flex.aplicar_automatico(cur, cuenta) == 0                                                   # el resto no tiene precio: no se inventa un costo
            assert _fila(cur, cuenta, f"{p}-A", "MLA-A1") == (None, None, 0.0, 0.0) and flex.contar_pendientes(cur, cuenta) == antes
            raise _Revertir()
    except _Revertir:
        pass

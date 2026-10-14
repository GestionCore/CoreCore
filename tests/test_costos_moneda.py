"""
Costo de fabricación en pesos o dólares, por publicación o por variante (costos_moneda.py, migración 0050).
Lo central: `precio_costo` sigue siendo el costo en PESOS que lee la Ganancia Real; en dólares es costo_original × la cotización activa y se recalcula cuando esa cotización cambia;
el costo de una variante manda sobre el de su publicación. Números calculados a mano; lo que toca la base corre contra la base real dentro de una transacción que se revierte
(la migración 0050 se aplica ahí adentro, así la prueba no depende de que ya esté aplicada).
"""
import os

import psycopg
import pytest

import costos_moneda as cm

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


# ── Montos, monedas y la conversión a pesos ──────────────────────────────────────────────────────────────────────────────────────────

def test_el_monto_se_valida_y_la_moneda_solo_puede_ser_pesos_o_dolares():
    assert cm.normalizar_monto("12.5") == 12.5 and cm.normalizar_monto(0) == 0.0 and cm.normalizar_monto("1234.567") == 1234.57
    for malo in ("abc", None, "", -1, "nan", "inf", 1e12):
        assert cm.normalizar_monto(malo) is None, malo
    assert cm.normalizar_moneda("usd") == "USD" and cm.normalizar_moneda(" ars ") == "ARS" and cm.normalizar_moneda(None) is None and cm.normalizar_moneda("") is None
    assert cm.normalizar_moneda("EUR") is False and cm.normalizar_moneda("pesos") is False


def test_un_costo_en_dolares_se_lleva_a_pesos_con_la_cotizacion_y_sin_cotizacion_no_se_supone_ninguna():
    assert cm.a_pesos(100.5, "USD", 1539.4) == 154709.7                      # 100,5 × 1.539,4
    assert cm.a_pesos(10, "USD", "1500.55") == 15005.5 and cm.a_pesos(0.01, "USD", 1500) == 15.0
    assert cm.a_pesos(8000, "ARS", None) == 8000.0 and cm.a_pesos(8000, "ARS", 1500) == 8000.0          # en pesos la cotización no importa
    assert cm.a_pesos(10, "USD", None) is None and cm.a_pesos(10, "USD", 0) is None and cm.a_pesos(10, "USD", -5) is None and cm.a_pesos(10, "USD", "abc") is None


def test_el_costo_de_una_venta_es_el_de_su_variante_si_tiene_uno_propio_y_si_no_el_de_la_publicacion():
    item = {"MLA1": 5000.0, "MLA2": None, "MLA3": 700.0}
    variante = {"55": 8000.0, "MLA3_unica": 900.0}
    assert cm.costo_de_venta("MLA1", "55", item, variante) == 8000.0              # la variante manda
    assert cm.costo_de_venta("MLA1", "56", item, variante) == 5000.0              # otra variante de la misma publicación, sin costo propio: el de la publicación
    assert cm.costo_de_venta("MLA3", "", item, variante) == 900.0                 # sin variaciones, la variante es «<id>_unica»
    assert cm.costo_de_venta("MLA2", "", item, variante) == 0.0 and cm.costo_de_venta("NO-EXISTE", "", item, variante) == 0.0       # sin ningún costo: 0, no rompe
    assert cm.costo_de_venta("MLA1", "55", item, {"55": 0}) == 5000.0 and cm.costo_de_venta("MLA1", "55", item, {"55": None}) == 5000.0   # un costo propio de 0 o vacío no cuenta


# ── El código tolera que la migración 0050 todavía no esté ───────────────────────────────────────────────────────────────────────────────

class _Transaccion:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conexion:
    def transaction(self):
        return _Transaccion()


class _CursorSinColumna:
    """Un cursor al que le falta la columna `costo_original`: lo que la menciona falla, el resto anda."""
    def __init__(self):
        self.connection, self.sentencias, self.rowcount = _Conexion(), [], 1

    def execute(self, sql, params=None):
        if "costo_original" in sql:
            raise psycopg.errors.UndefinedColumn("column costo_original does not exist")
        self.sentencias.append(" ".join(sql.split()))


def test_sin_la_migracion_los_costos_en_pesos_se_guardan_como_siempre_y_los_de_dolares_avisan():
    cur = _CursorSinColumna()
    assert cm.guardar_costo_publicacion(cur, 7, "MLA1", 8000, "ARS") == (True, "Costo guardado.", 1)
    assert cur.sentencias == ["UPDATE productos_padre SET precio_costo = %s WHERE cuenta_id = %s AND id_meli = ANY(%s)"]
    assert cm.guardar_costo_publicacion(cur, 7, "MLA1", 10, "USD", 1500) == (False, cm.MENSAJE_SIN_MIGRACION, 0)
    assert cm.guardar_costo_variante(cur, 7, "55", 10, "USD", 1500) == (False, cm.MENSAJE_SIN_MIGRACION, 0)
    assert cm.guardar_costo_variante(cur, 7, "55", 6000, "ARS")[0] is True and cm.recalcular_cuenta(cur, 7, 1500) == 0


def test_un_costo_invalido_no_toca_la_base():
    cur = _CursorSinColumna()
    assert cm.guardar_costo_publicacion(cur, 7, "MLA1", "abc")[0] is False and cm.guardar_costo_publicacion(cur, 7, "MLA1", -5)[0] is False
    assert cm.guardar_costo_publicacion(cur, 7, "MLA1", 10, "EUR")[0] is False
    assert cm.guardar_costo_publicacion(cur, 7, "MLA1", 10, "USD", None) == (False, cm.MENSAJE_SIN_DOLAR, 0)                  # dólares sin cotización
    assert cur.sentencias == []


# ── Contra la base real ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def _migrar(cur):
    cur.execute(open(os.path.join(RAIZ, "migrations", "0050_costo_original.sql"), encoding="utf-8").read())


def _padre(cur, cuenta, id_meli, costo=None):
    cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, precio_costo) VALUES (%s, %s, 'Prueba', 20000, %s) RETURNING id", (cuenta, id_meli, costo))
    return cur.fetchone()[0]


def _variante(cur, cuenta, id_padre, id_variante, costo=None):
    cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, etiqueta, precio_costo) VALUES (%s, %s, %s, 'Rojo', %s)", (cuenta, id_variante, id_padre, costo))


def _estado(cur, tabla, columna_id, valor, cuenta):
    cur.execute(f"SELECT precio_costo, costo_original, moneda_costo FROM {tabla} WHERE cuenta_id = %s AND {columna_id} = %s", (cuenta, valor))
    pesos, original, moneda = cur.fetchone()
    return (float(pesos) if pesos is not None else None, float(original) if original is not None else None, moneda)


@pytest.mark.db
@CON_BASE
def test_un_costo_en_dolares_se_guarda_en_pesos_y_se_recalcula_cuando_cambia_la_cotizacion():
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-MON-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:                       # la migración (DDL) la corre el administrador; todo se revierte
            cur = conexion.cursor()
            _migrar(cur)
            _padre(cur, cuenta, f"{p}-A")
            _padre(cur, cuenta, f"{p}-B", costo=3000)
            assert cm.guardar_costo_publicacion(cur, cuenta, f"{p}-A", 10, "USD", 1500) == (True, "Costo guardado.", 1)
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta) == (15000.0, 10.0, "USD")          # 10 US$ × 1.500
            assert cm.guardar_costo_publicacion(cur, cuenta, [f"{p}-A", f"{p}-B"], 8000, "ARS") == (True, "Costo guardado.", 2)    # varias a la vez, en pesos
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta) == (8000.0, 8000.0, "ARS")                # pasar a pesos pisa el dólar: la moneda queda bien
            assert cm.guardar_costo_publicacion(cur, cuenta, f"{p}-B", 20, "USD", 1500)[0] is True

            # el dólar sube a 1.600: solo el costo en dólares se recalcula (20 × 1.600); el de pesos no se toca
            assert cm.recalcular_cuenta(cur, cuenta, 1600) >= 1
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-B", cuenta) == (32000.0, 20.0, "USD")
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta) == (8000.0, 8000.0, "ARS")
            assert cm.recalcular_cuenta(cur, cuenta, 1600) == 0                                                   # repetir con la misma cotización no cambia nada
            assert cm.recalcular_cuenta(cur, cuenta, None) == 0 and cm.recalcular_cuenta(cur, cuenta, 0) == 0 and cm.recalcular_cuenta(cur, cuenta, "abc") == 0
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-B", cuenta)[0] == 32000.0                      # sin cotización nunca se pisa un costo con un número supuesto
            assert cm.guardar_costo_publicacion(cur, cuenta, f"{p}-B", 20, "USD", None)[0] is False
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_el_costo_de_una_variante_se_guarda_se_recalcula_y_se_quita_con_cero():
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-VAR-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            _migrar(cur)
            id_padre = _padre(cur, cuenta, f"{p}-A", costo=5000)
            _variante(cur, cuenta, id_padre, f"{p}-V1")
            _variante(cur, cuenta, id_padre, f"{p}-V2")
            assert cm.guardar_costo_variante(cur, cuenta, f"{p}-V1", 7, "USD", 1500) == (True, "Costo guardado.", 1)
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V1", cuenta) == (10500.0, 7.0, "USD")
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V2", cuenta) == (None, None, None)       # la otra variante sigue sin costo propio
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta)[0] == 5000.0                          # y el de la publicación no se toca
            cm.recalcular_cuenta(cur, cuenta, 1600)
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V1", cuenta)[0] == 11200.0                # 7 × 1.600
            assert cm.guardar_costo_variante(cur, cuenta, f"{p}-V1", 0)[0] is True
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V1", cuenta) == (None, None, None)       # 0 = vuelve a usar el costo de la publicación
            assert cm.guardar_costo_variante(cur, cuenta, f"{p}-V2", 9000, "ARS")[0] is True and cm.guardar_costo_variante(cur, cuenta, f"{p}-V2", 5, "USD", None)[0] is False
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_la_base_no_deja_un_costo_en_dolares_sin_su_valor_en_dolares():
    import db
    usuario, cuenta = _cuenta()
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            _migrar(cur)
            _padre(cur, cuenta, "PRUEBA-CHK-1")
            with pytest.raises(psycopg.errors.CheckViolation):
                with conexion.transaction():
                    cur.execute("UPDATE productos_padre SET moneda_costo = 'USD', costo_original = NULL WHERE cuenta_id = %s AND id_meli = 'PRUEBA-CHK-1'", (cuenta,))
            raise _Revertir()
    except _Revertir:
        pass


# ── La rentabilidad: el costo que usa cada venta ─────────────────────────────────────────────────────────────────────────────────────────

def test_la_ganancia_real_usa_el_costo_de_la_variante_vendida():
    from tests.test_ganancia_real import _datos
    import ads
    import db
    import facturacion
    import metricas
    from unittest import mock
    datos = _datos()
    # o1 (2 u. de MLA1, variante v-o1) tiene costo propio de 6.000 en vez de los 4.000 de la publicación; v-o2 trae 0 (no cuenta: usa los 4.000)
    datos["variantes"] = [{"id_variante": "v-o1", "talle": "M", "color": "Negro", "precio_costo": 6000}, {"id_variante": "v-o2", "talle": "L", "color": "Único", "precio_costo": 0}]
    # o4 (MLA3) no tiene variaciones (id_variante vacío): su variante es «MLA3_unica», con costo propio de 7.000 en vez de los 8.000 de la publicación
    datos["ventas"][3]["id_variante"] = ""
    datos["variantes"].append({"id_variante": "MLA3_unica", "talle": None, "color": None, "precio_costo": 7000})
    from tests.test_ganancia_real import _Conexion
    with mock.patch.object(db, "conexion_usuario", lambda *a, **k: _Conexion(datos)), mock.patch.object(ads, "obtener_advertiser_id", lambda *a: "A1"), \
            mock.patch.object(ads, "obtener_costos_ads_por_item", lambda *a, **k: {"MLA1": 900.0, "MLA3": 500.0}), mock.patch.object(ads, "obtener_gasto_ads_total_periodo", lambda *a, **k: 2000.0), \
            mock.patch.object(facturacion, "cargos_fuera_de_ventas", lambda *a, **k: {"total": 1234.5, "items": [], "completo": True}):
        r = metricas.calcular_ganancia_real(1, 1, "token", "2026-09-01", "2026-09-30")
    por_orden = {v["id_orden"]: v["raw"] for v in r["ventas"]}
    assert por_orden["o1"]["costo_fabricacion"] == 12000.0 and por_orden["o1"]["ganancia_neta"] == 3900.0       # 20.000 − 2.000 − 1.500 − 600 − 2×6.000
    assert por_orden["o2"]["costo_fabricacion"] == 4000.0 and por_orden["o2"]["ganancia_neta"] == 4000.0         # costo propio 0 = sin costo propio: el de la publicación
    assert por_orden["o3"]["costo_fabricacion"] == 0.0                                                            # sin ningún costo cargado cuenta 0, como siempre
    assert por_orden["o4"]["costo_fabricacion"] == 7000.0 and por_orden["o4"]["ganancia_neta"] == 7500.0         # 20.000 − 3.000 − 2.000 − 500 − 7.000
    raw = r["resumen"]["raw"]
    assert raw["costo_fabricacion"] == 23000.0 and raw["ganancia_neta_ventas"] == 30250.0 - 4000.0 + 1000.0      # 12.000 + 4.000 + 0 + 7.000; 3.900 + 4.000 + 11.850 + 7.500
    assert raw["ganancia_neta"] == round(raw["facturado"] - raw["comision"] - raw["envios"] - raw["costo_ads"] - raw["costo_fabricacion"] - raw["cargos_fuera_de_ventas"], 2)       # la fórmula, intacta


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma al salir: lo que lee o escribe el código bajo prueba se revierte al final."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


def _ventas_de_prueba(cur, cuenta, p):
    id_a = _padre(cur, cuenta, f"{p}-A", costo=1000)
    _padre(cur, cuenta, f"{p}-B", costo=500)
    _variante(cur, cuenta, id_a, f"{p}-V1", costo=1500)                  # la variante V1 cuesta 1.500; la V2 no tiene costo propio (usa los 1.000 de la publicación)
    _variante(cur, cuenta, id_a, f"{p}-V2")
    for orden, id_meli, variante, cantidad, logistica in ((f"{p}-1", f"{p}-A", f"{p}-V1", 2, "fulfillment"), (f"{p}-2", f"{p}-A", f"{p}-V2", 1, "drop_off"), (f"{p}-3", f"{p}-B", "", 4, "drop_off")):
        cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen, tipo_logistica)
                       VALUES (%s, %s, %s, %s, 't', %s, 10000, '2030-03-15', 'meli', %s)""", (cuenta, orden, id_meli, variante, cantidad, logistica))


@pytest.mark.db
@CON_BASE
def test_el_reporte_fiscal_el_comparador_y_la_cobertura_usan_el_costo_de_la_variante(monkeypatch):
    import comparador_logistica
    import costos
    import db
    import reporte_fiscal
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-REN-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            monkeypatch.setattr(db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            _ventas_de_prueba(cur, cuenta, p)
            # costo del mes: 2 u. de V1 × 1.500 + 1 u. de V2 × 1.000 (el de la publicación) + 4 u. de B × 500 (sin variaciones: «B_unica» no tiene costo propio) = 3.000 + 1.000 + 2.000
            marzo = reporte_fiscal.calcular_reporte_anual(usuario, 2030, cuenta)[2]
            assert marzo["mes"] == 3 and marzo["costo_fabricacion"] == 6000.0 and marzo["unidades"] == 7 and marzo["costo_fab_f"] == "6.000"
            # el comparador reparte por canal: FULL = la venta de V1 (3.000); el resto (clásico) = 1.000 + 2.000
            grupos, _ = comparador_logistica.calcular_comparacion(usuario, cuenta, None, "2030-03-01", "2030-03-31")
            por_canal = {g["nombre"]: g["costo_fab_formateado"] for g in grupos}
            assert por_canal["FULL"] == "3.000" and por_canal["Envíos clásicos"] == "3.000"
            # cobertura: las tres ventas tienen costo (la de V1 por su variante, las otras por su publicación): nada sin costo; sin el de la variante ni el de la publicación, sí cuenta
            assert costos.cobertura_de_costos(cur, "2030-03-01", "2030-03-31")["sin_costo"] == 0.0
            cur.execute("UPDATE productos_padre SET precio_costo = 0 WHERE cuenta_id = %s AND id_meli = %s", (cuenta, f"{p}-B"))
            cobertura = costos.cobertura_de_costos(cur, "2030-03-01", "2030-03-31")
            assert cobertura["sin_costo"] == 40000.0 and cobertura["publicaciones"] == 1                         # los 4 × 10.000 de B, que quedó sin ningún costo
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_sin_costos_por_variante_el_costo_de_cada_consulta_es_exactamente_el_de_siempre():
    """Regresión con los datos REALES (solo lectura): sumar el costo con la expresión nueva da lo mismo que con la de antes (COALESCE(p.precio_costo, 0)) cuando ninguna variante tiene costo propio."""
    import db
    with db.conexion_admin() as conexion:
        cur = conexion.cursor()
        cur.execute("SELECT COUNT(*) FROM productos_variantes WHERE NULLIF(precio_costo, 0) IS NOT NULL")
        con_costo_propio = cur.fetchone()[0]
        join_variante, costo = cm.sql_costo_de_venta()
        cur.execute(f"""SELECT v.cuenta_id, COALESCE(SUM(COALESCE(p.precio_costo, 0) * v.cantidad), 0), COALESCE(SUM({costo} * v.cantidad), 0), COUNT(*)
                        FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id {join_variante} GROUP BY v.cuenta_id""")
        filas = cur.fetchall()
        cur.execute("SELECT cuenta_id, COUNT(*) FROM ventas GROUP BY cuenta_id")
        ventas = dict(cur.fetchall())
    assert filas and all(n == ventas[cuenta] for cuenta, _, _, n in filas)                  # el JOIN de la variante no duplica ni pierde ninguna venta
    if con_costo_propio == 0:
        assert all(float(antes) == float(ahora) for _, antes, ahora, _ in filas)
    else:
        pytest.skip("Hay variantes con costo propio cargado: la comparación con el costo de antes ya no tiene por qué dar igual")


def test_ninguna_escritura_de_costo_toca_precio_costo_por_su_cuenta():
    """Todo costo se escribe con costos_moneda: un UPDATE de precio_costo suelto dejaría una moneda vieja y el próximo recálculo pisaría lo que la persona acaba de cargar."""
    import glob
    sueltos = []
    for ruta in glob.glob(os.path.join(RAIZ, "*.py")) + glob.glob(os.path.join(RAIZ, "auth", "*.py")):
        rel = os.path.relpath(ruta, RAIZ)
        if rel == "costos_moneda.py":
            continue
        fuente = open(ruta, encoding="utf-8").read()
        if "SET precio_costo" in fuente or "SET precio_costo=" in fuente:
            sueltos.append(rel)
    assert not sueltos, f"Escriben precio_costo sin pasar por costos_moneda.guardar_costo_*: {sueltos}"

"""
Envíos Flex que se pagaron y no se recuperan: una orden entregada con tu logística (Flex) que después se cancela o se devuelve (flex.py, ventas_sync.py, migración 0049).
Al cancelarse, la orden sale de `ventas` y su costo de entrega desaparecía de todos los números: ahora queda como gasto operativo irrecuperable (una sola vez por orden), y el costo
del envío de vuelta lo carga la persona. Números hechos a mano; lo que toca la base corre contra la base real dentro de una transacción que se revierte (la migración 0049 se aplica ahí adentro).
"""
import os
from datetime import date

import pytest

import flex
import ventas_sync

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


# ── Qué órdenes cuentan como envío perdido ───────────────────────────────────────────────────────────────────────────────────────────

def test_solo_cuenta_la_orden_flex_que_ya_salio_y_tiene_costo_cargado():
    filas = [
        ("A", "self_service", True, 1800.0, "2030-03-01"), ("A", "self_service", True, 900.0, "2030-03-01"),          # una orden con 2 ítems: se suma lo de los dos
        ("B", "self_service", False, 2000.0, "2030-03-02"),                                                           # se canceló ANTES de salir: no costó nada
        ("C", "fulfillment", True, 5000.0, "2030-03-03"),                                                             # FULL: lo paga Mercado Libre, no es un costo de entrega propio
        ("D", "self_service", True, 0, "2030-03-04"), ("E", "self_service", True, None, "2030-03-04"),               # sin costo asignado: no se inventa
        ("F", None, True, 700.0, "2030-03-05"),
    ]
    assert flex.perdidas_por_orden(filas) == [("A", 2700.0, "2030-03-01")]
    assert flex.perdidas_por_orden([]) == []


# ── Contra la base real ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def _migrar(cur):
    cur.execute(open(os.path.join(RAIZ, "migrations", "0049_gastos_origen.sql"), encoding="utf-8").read())


HOY = date(2030, 3, 10)


@pytest.mark.db
@CON_BASE
def test_el_envio_de_ida_se_anota_una_sola_vez_y_el_de_vuelta_se_carga_corrige_y_quita():
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-FLEXP-{os.getpid()}"
    filas = [(f"{p}-A", "self_service", True, 1800.0, "2030-03-01"), (f"{p}-A", "self_service", True, 900.0, "2030-03-01"), (f"{p}-B", "self_service", False, 2000.0, "2030-03-02")]
    try:
        with db.conexion_admin() as conexion:                      # el DDL de la migración lo puede hacer solo el administrador; todo se revierte
            cur = conexion.cursor()
            _migrar(cur)
            assert flex.registrar_envios_perdidos(cur, cuenta, filas, HOY) == 1                    # solo la orden A salió; la B se canceló antes
            assert flex.registrar_envios_perdidos(cur, cuenta, filas, HOY) == 0                    # repetirlo no duplica nada
            cur.execute("SELECT concepto, categoria, monto, fecha, origen, referencia FROM gastos_operativos WHERE cuenta_id = %s AND referencia LIKE %s", (cuenta, f"{p}-%"))
            (concepto, categoria, monto, fecha, origen, referencia), = cur.fetchall()
            assert (categoria, float(monto), fecha, origen, referencia) == ("variable", 2700.0, HOY, "flex_ida", f"{p}-A") and "no se recupera" in concepto

            assert flex.envios_perdidos(cur, cuenta, "2030-03-01", "2030-03-31") == [{"id_orden": f"{p}-A", "fecha": HOY, "ida": 2700.0, "vuelta": None}]
            assert flex.envios_perdidos(cur, cuenta, "2030-04-01", "2030-04-30") == []             # fuera del período

            assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-NO", 5000, HOY) == (False, "Esa orden no está entre tus envíos Flex devueltos o cancelados.")
            assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-B", 5000, HOY)[0] is False      # la B nunca salió: no tiene envío de ida registrado
            for malo in ("abc", None, -1, float("nan"), 20_000_000):
                assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-A", malo, HOY)[0] is False, malo
            assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-A", 6500, HOY) == (True, "Guardamos el costo de vuelta.")
            assert flex.envios_perdidos(cur, cuenta, "2030-03-01", "2030-03-31")[0]["vuelta"] == 6500.0
            assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-A", 7000.5, HOY)[0] is True      # corregirlo cambia el monto, no agrega otro gasto
            cur.execute("SELECT COUNT(*), SUM(monto) FROM gastos_operativos WHERE cuenta_id = %s AND origen = 'flex_vuelta' AND referencia = %s", (cuenta, f"{p}-A"))
            assert (cur.fetchone()[0], ) == (1, )
            assert flex.envios_perdidos(cur, cuenta, "2030-03-01", "2030-03-31")[0]["vuelta"] == 7000.5
            assert flex.guardar_costo_de_vuelta(cur, cuenta, f"{p}-A", 0, HOY) == (True, "Quitamos el costo de vuelta.")
            assert flex.envios_perdidos(cur, cuenta, "2030-03-01", "2030-03-31")[0]["vuelta"] is None

            # los gastos que carga la persona a mano (sin origen) no entran en la clave única: puede haber todos los que quiera
            for _ in range(2):
                cur.execute("INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha) VALUES (%s, 'Bolsas', 'variable', 100, %s)", (cuenta, HOY))
            raise _Revertir()
    except _Revertir:
        pass


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma al salir: lo que escribe el sync se revierte al final de la prueba."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


def _venta(cur, cuenta, orden, id_meli, tipo, despachado, costo_flex, dia="2030-03-05"):
    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen, tipo_logistica, despachado, costo_flex, costo_envio)
                   VALUES (%s, %s, %s, '', 't', 1, 20000, %s, 'meli', %s, %s, %s, %s)""", (cuenta, orden, id_meli, dia, tipo, despachado, costo_flex, costo_flex))


@pytest.mark.db
@CON_BASE
def test_el_sync_anota_el_envio_flex_de_la_orden_que_ya_salio_cuando_la_retira(monkeypatch):
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-FLEXS-{os.getpid()}"
    ordenes = [{"id": f"{p}-{n}"} for n in ("A", "B", "C")]
    monkeypatch.setattr(ventas_sync, "_ordenes_canceladas", lambda *a, **k: ordenes)
    monkeypatch.setattr(ventas_sync, "hoy_argentina", lambda: HOY)
    try:
        with db.conexion_admin() as conexion:
            monkeypatch.setattr(ventas_sync.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            _migrar(cur)
            _venta(cur, cuenta, f"{p}-A", f"{p}-MLA1", "self_service", True, 1800)          # Flex que ya salió: se paga
            _venta(cur, cuenta, f"{p}-B", f"{p}-MLA1", "self_service", False, 1800)         # Flex que no llegó a salir: no
            _venta(cur, cuenta, f"{p}-C", f"{p}-MLA1", "fulfillment", True, 0)              # FULL: no es costo propio
            assert ventas_sync.retirar_ventas_canceladas(usuario, cuenta, "tok", 99) == 3
            cur.execute("SELECT referencia, monto, origen FROM gastos_operativos WHERE cuenta_id = %s AND referencia LIKE %s", (cuenta, f"{p}-%"))
            assert [(r, float(m), o) for r, m, o in cur.fetchall()] == [(f"{p}-A", 1800.0, "flex_ida")]
            cur.execute("SELECT COUNT(*) FROM ventas WHERE id_orden LIKE %s", (f"{p}-%",))
            assert cur.fetchone()[0] == 0
            assert ventas_sync.retirar_ventas_canceladas(usuario, cuenta, "tok", 99) == 0     # una segunda pasada no vuelve a anotar nada
            cur.execute("SELECT COUNT(*) FROM gastos_operativos WHERE cuenta_id = %s AND referencia LIKE %s", (cuenta, f"{p}-%"))
            assert cur.fetchone()[0] == 1
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_si_no_se_puede_anotar_el_gasto_la_retirada_de_las_ventas_no_se_pierde(monkeypatch):
    """Anotar el envío perdido es secundario: si falla (p. ej. la migración 0049 todavía no se aplicó), las ventas canceladas igual salen de `ventas` y la conexión sigue sirviendo."""
    import db
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-FLEXF-{os.getpid()}"
    monkeypatch.setattr(ventas_sync, "_ordenes_canceladas", lambda *a, **k: [{"id": f"{p}-A"}])

    def falla(cursor, cuenta_id, filas, hoy):
        cursor.execute("SELECT esta_columna_no_existe FROM gastos_operativos")        # un error de SQL de verdad: deja la transacción abortada si no hay punto de guardado
    monkeypatch.setattr(ventas_sync.flex, "registrar_envios_perdidos", falla)
    try:
        with db.conexion_admin() as conexion:
            monkeypatch.setattr(ventas_sync.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            _venta(cur, cuenta, f"{p}-A", f"{p}-MLA1", "self_service", True, 1800)
            assert ventas_sync.retirar_ventas_canceladas(usuario, cuenta, "tok", 99) == 1
            cur.execute("SELECT COUNT(*) FROM ventas WHERE id_orden = %s", (f"{p}-A",))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM ventas_retiradas WHERE id_orden = %s AND motivo = 'cancelada'", (f"{p}-A",))
            assert cur.fetchone()[0] == 1                                              # y quedó archivada: la transacción no se abortó
            raise _Revertir()
    except _Revertir:
        pass


def test_la_migracion_agrega_origen_y_referencia_con_clave_unica_solo_para_lo_automatico():
    sql = open(os.path.join(RAIZ, "migrations", "0049_gastos_origen.sql"), encoding="utf-8").read()
    assert "ADD COLUMN IF NOT EXISTS origen TEXT" in sql and "ADD COLUMN IF NOT EXISTS referencia TEXT" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_gastos_origen_referencia ON gastos_operativos (cuenta_id, origen, referencia) WHERE origen IS NOT NULL" in sql


@pytest.mark.db
@CON_BASE
def test_el_endpoint_del_costo_de_vuelta_y_el_panel_de_costos(monkeypatch):
    import app as a
    usuario, cuenta = _cuenta()
    cliente = a.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario, cuenta
    post = lambda cuerpo: cliente.post("/api/flex/costo_vuelta", json=cuerpo, headers={"Sec-Fetch-Site": "same-origin"})
    assert post({"id_orden": "NO-EXISTE-XYZ", "monto": 100}).status_code == 400
    assert post({"id_orden": "", "monto": 100}).get_json()["ok"] is False and post({"id_orden": "X", "monto": "abc"}).status_code == 400
    assert a.auditoria.ETIQUETAS["flex_costo_vuelta"]

    monkeypatch.setattr(a.flex, "envios_perdidos", lambda cursor, cuenta_id, desde, hasta: [{"id_orden": "2000099", "fecha": date(2026, 10, 12), "ida": 1800.0, "vuelta": 6500.0}])
    html = cliente.get("/costos").get_data(as_text=True)
    assert 'id="flex-devueltos"' in html and "2000099" in html and 'data-click="guardarCostoVueltaFlex"' in html and 'value="6500"' in html
    monkeypatch.setattr(a.flex, "envios_perdidos", lambda cursor, cuenta_id, desde, hasta: [])
    assert 'id="flex-devueltos"' not in cliente.get("/costos").get_data(as_text=True)               # sin envíos perdidos, la sección no aparece

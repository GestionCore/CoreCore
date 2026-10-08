"""
Cómo `ventas_sync` arma lo que cuesta cada venta: comisión + financiación + cupones del vendedor, retenciones de impuestos, lo que Mercado Libre depositó, y el reparto del envío entre los ítems
que lo comparten. Es la materia prima de Ganancia Real (que coincide con el depósito real al 0,31 %): sin estas pruebas un cambio acá movía la ganancia de todos sin que nada lo notara
(ventas_sync.py tenía 33 % de cobertura). Los números esperados están calculados a mano en los comentarios.
"""
import os

import pytest

import meli_http
import ventas_sync

CACHES = ("_cache_pago", "_cache_shipment", "_cache_provincia_envio", "_cache_tipo_logistica", "_cache_ubicacion_envio", "_cache_costo_envio_vendedor")


@pytest.fixture(autouse=True)
def caches_limpias():
    for nombre in CACHES:
        getattr(ventas_sync, nombre).clear()
    yield
    for nombre in CACHES:
        getattr(ventas_sync, nombre).clear()


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo or {}

    def json(self):
        return self._cuerpo


def _pago(neto=16200, estado="approved", cargos=None, liberacion="2026-09-24T12:00:00.000-04:00"):
    return {"status": estado, "transaction_details": {"net_received_amount": neto}, "money_release_date": liberacion, "charges_details": cargos if cargos is not None else []}


CARGOS_REALES = [
    {"type": "tax", "name": "iibb_retencion", "amounts": {"original": 300, "refunded": 0}},                                       # retención de impuestos: se muestra aparte
    {"type": "coupon", "name": "cupon", "accounts": {"from": "collector"}, "amounts": {"original": 500, "refunded": 100}},       # lo financia el VENDEDOR: 500 − 100 reembolsados = 400
    {"type": "coupon", "name": "cupon_meli", "accounts": {"from": "ml"}, "amounts": {"original": 700}},                          # lo financia MeLi al comprador: no le cuesta nada al vendedor
    {"type": "fee", "name": "financing_add_on_fee", "accounts": {"from": "collector"}, "amounts": {"original": 250}},            # costo de ofrecer cuotas
    {"type": "fee", "name": "mercadopago_fee", "accounts": {"from": "collector"}, "amounts": {"original": 999}},                 # otro cargo: no entra en ninguno de los tres
]


# ── Lo que informa Mercado Pago de cada pago ─────────────────────────────────────────────────────────────────────────────────

def test_el_pago_separa_retenciones_cupones_del_vendedor_financiacion_y_lo_depositado(monkeypatch):
    monkeypatch.setattr(meli_http, "get", lambda url, **kw: _Resp(200, _pago(cargos=CARGOS_REALES)))
    assert ventas_sync._datos_de_pago("tok", 111) == {"retenciones": 300.0, "cupones": 400.0, "financiacion": 250.0, "neto": 16200.0, "liberacion": "2026-09-24"}


def test_un_pago_no_aprobado_sin_neto_o_que_falla_no_da_datos(monkeypatch):
    monkeypatch.setattr(meli_http, "get", lambda url, **kw: _Resp(200, _pago(estado="in_process")))
    assert ventas_sync._datos_de_pago("tok", 1) is None
    monkeypatch.setattr(meli_http, "get", lambda url, **kw: _Resp(200, {"status": "approved", "transaction_details": {}}))
    assert ventas_sync._datos_de_pago("tok", 2) is None
    monkeypatch.setattr(meli_http, "get", lambda url, **kw: _Resp(503))
    assert ventas_sync._datos_de_pago("tok", 3) is None

    def _rompe(url, **kw):
        raise ConnectionError("se cortó")
    monkeypatch.setattr(meli_http, "get", _rompe)
    assert ventas_sync._datos_de_pago("tok", 4) is None                           # nunca levanta: la sincronización sigue
    assert ventas_sync._cache_pago == {}                                          # y un fallo no queda guardado como «sin datos» para siempre


def test_el_pago_consultado_se_guarda_y_no_se_vuelve_a_pedir(monkeypatch):
    llamadas = []
    monkeypatch.setattr(meli_http, "get", lambda url, **kw: llamadas.append(url) or _Resp(200, _pago(cargos=[])))
    ventas_sync._datos_de_pago("tok", 7)
    ventas_sync._datos_de_pago("tok", 7)
    assert len(llamadas) == 1


# ── De una orden de Mercado Libre a las filas de `ventas` ───────────────────────────────────────────────────────────────────

def _orden(**extra):
    base = {"id": 2000001, "status": "paid", "date_created": "2026-09-10T14:35:00.000-04:00",
            "order_items": [
                {"item": {"id": "MLA1", "title": "Campera Negra", "variation_id": 77}, "quantity": 1, "unit_price": 10000, "sale_fee": 1500},
                {"item": {"id": "MLA2", "title": "Termo Acero", "variation_id": None}, "quantity": 2, "unit_price": 5000, "sale_fee": 1800},
            ],
            "shipping": {"id": 555, "status": "delivered"}, "payments": [{"id": 9001, "installments": 3}], "buyer": {"nickname": "COMPRADOR", "first_name": "Ana"}}
    base.update(extra)
    return base


def _preparar(monkeypatch, logistica="fulfillment", envio_vendedor=3000.0, costo_envio_reportado=2000.0, pago=True):
    monkeypatch.setattr(ventas_sync, "_obtener_costo_envio", lambda token, sid: costo_envio_reportado)
    ventas_sync._cache_tipo_logistica["555"] = logistica
    if envio_vendedor is not None:
        ventas_sync._cache_costo_envio_vendedor["555"] = envio_vendedor
    if pago:
        # pago de 20.000 (10.000 + 2 × 5.000): retenciones 400, cupones 1.000, financiación 600, MeLi depositó 17.000
        ventas_sync._cache_pago[9001] = {"retenciones": 400.0, "cupones": 1000.0, "financiacion": 600.0, "neto": 17000.0, "liberacion": "2026-09-24"}


def test_los_cargos_de_la_orden_se_reparten_entre_sus_items_en_proporcion_a_lo_facturado(monkeypatch):
    _preparar(monkeypatch)
    a, b = ventas_sync._extraer_filas_de_orden(_orden(), "tok")
    # facturado de la orden = 10.000 + 2 × 5.000 = 20.000; cada ítem pesa 0,5
    assert (a["precio_venta"], a["cantidad"], b["precio_venta"], b["cantidad"]) == (10000.0, 1, 5000.0, 2)
    assert a["cupones"] == 500.0 and b["cupones"] == 500.0                         # 1.000 × 0,5
    assert a["cargo_venta"] == 2000.0 and b["cargo_venta"] == 2300.0               # comisión + cupones del vendedor: 1.500 + 500 y 1.800 + 500
    assert a["financiacion"] == 300.0 and b["financiacion"] == 300.0               # 600 × 0,5 (ya está DENTRO del sale_fee: es un desglose)
    assert a["retenciones"] == 200.0 and b["retenciones"] == 200.0                 # 400 × 0,5
    assert a["neto_recibido"] == 8500.0 and b["neto_recibido"] == 8500.0           # 17.000 × 0,5
    assert a["costo_envio"] == 1000.0 and b["costo_envio"] == 1000.0               # el costo de envío reportado (2.000) también por proporción
    assert a["fecha_liberacion"] == "2026-09-24" and a["pago_id"] == 9001
    assert a["cuotas"] == 3 and a["id_variante"] == "77" and b["id_variante"] == ""   # sin variación el id es texto vacío, nunca None


def test_los_cargos_de_los_items_suman_los_de_la_orden(monkeypatch):
    _preparar(monkeypatch)
    filas = ventas_sync._extraer_filas_de_orden(_orden(), "tok")
    assert sum(f["cargo_venta"] for f in filas) == 1500 + 1800 + 1000             # comisiones + cupones: no se pierde ni se inventa un peso
    assert sum(f["retenciones"] for f in filas) == 400 and sum(f["neto_recibido"] for f in filas) == 17000


def test_el_costo_real_del_envio_depende_de_la_logistica(monkeypatch):
    _preparar(monkeypatch, logistica="fulfillment", envio_vendedor=3000.0)
    assert {f["envio_shipment_total"] for f in ventas_sync._extraer_filas_de_orden(_orden(), "tok")} == {3000.0}   # FULL/correo: lo que cobra MeLi (se reparte después)
    _preparar(monkeypatch, logistica="self_service")
    assert {f["envio_shipment_total"] for f in ventas_sync._extraer_filas_de_orden(_orden(), "tok")} == {0.0}      # Flex: MeLi no cobra envío: lo cobra la logística propia
    ventas_sync._cache_tipo_logistica.clear()
    assert {f["envio_shipment_total"] for f in ventas_sync._extraer_filas_de_orden(_orden(), "tok")} == {None}     # logística todavía desconocida: se completa más tarde, no se inventa


def test_si_falta_el_pago_de_algun_item_no_se_inventan_retenciones_ni_neto(monkeypatch):
    _preparar(monkeypatch, pago=False)
    orden = _orden(payments=[{"id": 9001, "installments": 1}, {"id": 9002, "installments": 1}])
    ventas_sync._cache_pago[9001] = {"retenciones": 1.0, "cupones": 0.0, "financiacion": 0.0, "neto": 5.0, "liberacion": None}      # el 9002 no se pudo consultar
    for fila in ventas_sync._extraer_filas_de_orden(orden, "tok"):
        assert fila["retenciones"] is None and fila["neto_recibido"] is None and fila["cupones"] is None      # «no sabemos» no es «cero»: la conciliación los salta
        assert fila["cargo_venta"] in (1500.0, 1800.0)                                                        # solo la comisión informada por la orden


def test_una_orden_cancelada_sin_items_o_con_un_item_sin_id_no_genera_filas_invalidas(monkeypatch):
    _preparar(monkeypatch)
    assert ventas_sync._extraer_filas_de_orden(_orden(status="cancelled"), "tok") == []
    assert ventas_sync._extraer_filas_de_orden(_orden(status="invalid"), "tok") == []
    assert ventas_sync._extraer_filas_de_orden(_orden(order_items=[]), "tok") == []
    solo_uno = _orden()
    solo_uno["order_items"][1]["item"]["id"] = None
    assert [f["id_meli"] for f in ventas_sync._extraer_filas_de_orden(solo_uno, "tok")] == ["MLA1"]


def test_sin_comision_informada_no_se_suman_los_cupones_a_nada(monkeypatch):
    _preparar(monkeypatch)
    orden = _orden()
    orden["order_items"][0]["sale_fee"] = None
    a, b = ventas_sync._extraer_filas_de_orden(orden, "tok")
    assert a["cargo_venta"] is None and b["cargo_venta"] == 2300.0


# ── La hora de la venta: Mercado Libre manda -04:00 aunque Argentina es UTC−3 ──────────────────────────────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("2026-09-30T23:30:00.000-04:00", ("2026-10-01", "00:30:00")),      # 23:30 en -04:00 = 00:30 en Argentina: ya es el día siguiente
    ("2026-09-10T14:35:00.000-04:00", ("2026-09-10", "15:35:00")),
    ("2026-09-10T14:35:00.000-03:00", ("2026-09-10", "14:35:00")),      # ya en hora argentina: no se mueve
    ("2026-09-10T17:35:00Z", ("2026-09-10", "14:35:00")),               # UTC
    ("2026-09-10T14:35:00", ("2026-09-10", "14:35:00")),                # sin offset se asume hora argentina
])
def test_la_hora_de_la_venta_se_convierte_a_hora_argentina(entrada, esperado):
    assert ventas_sync._fecha_hora_argentina(entrada) == esperado


def test_una_fecha_ilegible_no_rompe_la_sincronizacion():
    fecha, hora = ventas_sync._fecha_hora_argentina("basura")
    assert len(fecha) == 10 and len(hora) == 8
    assert ventas_sync._fecha_hora_argentina(None)[0]


# ── El reparto del costo de envío en la base (SQL real, todo revertido) ──────────────────────────────────────────────────────

class _Revertir(Exception):
    pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_el_costo_del_envio_se_reparte_en_proporcion_a_lo_facturado_y_suma_el_costo_flex():
    import db
    lote = f"PRUEBA-{os.getpid()}"
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            # Un envío de $3.000 compartido por tres filas que facturaron 10.000, 20.000 y 10.000 (reparto 25 % / 50 % / 25 %); la tercera además lleva $400 de Flex
            filas = [(f"{lote}-1", 10000, 1, 0), (f"{lote}-2", 10000, 2, 0), (f"{lote}-3", 10000, 1, 400)]
            for orden, precio, cantidad, flex in filas:
                cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, cantidad, precio_venta, fecha_venta, shipment_id, envio_shipment_total, costo_flex, costo_envio, origen)
                               VALUES (%s, %s, 'MLA-PRUEBA', %s, %s, '2026-09-10', %s, 3000, %s, 7, 'meli')""", (cuenta, orden, cantidad, precio, lote, flex))
            ventas_sync._repartir_envios(cur, cuenta, [lote, lote, None, ""])
            cur.execute("SELECT id_orden, costo_envio_meli, costo_envio, costo_envio_original FROM ventas WHERE shipment_id = %s ORDER BY id_orden", (lote,))
            resultado = {fila[0].split("-")[-1]: fila[1:] for fila in cur.fetchall()}
            assert float(resultado["1"][0]) == 750.0 and float(resultado["1"][1]) == 750.0         # 3.000 × 10.000 ÷ 40.000
            assert float(resultado["2"][0]) == 1500.0 and float(resultado["2"][1]) == 1500.0       # 3.000 × 20.000 ÷ 40.000
            assert float(resultado["3"][0]) == 750.0 and float(resultado["3"][1]) == 1150.0        # 750 de MeLi + 400 de Flex
            assert float(resultado["1"][2]) == 7.0                                                  # guarda el valor anterior la primera vez
            assert sum(float(r[0]) for r in resultado.values()) == 3000.0                          # la parte de MeLi cierra con el costo del envío: ni un peso de más ni de menos
            ventas_sync._repartir_envios(cur, cuenta, [lote])                                       # repetirlo no cambia nada ni pisa el valor original
            cur.execute("SELECT costo_envio, costo_envio_original FROM ventas WHERE id_orden = %s", (f"{lote}-1",))
            costo, original = cur.fetchone()
            assert float(costo) == 750.0 and float(original) == 7.0
            raise _Revertir()
    except _Revertir:
        pass

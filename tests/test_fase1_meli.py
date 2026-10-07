"""
Fase 1 de la auditoría (integración con Mercado Libre). Las formas de respuesta son las reales (se capturaron con GET de solo lectura el 2026-10-07):
shipping_preferences no trae `free_shipping_min_ticket` sino `mandatory_settings.price_limit` + `free_configurations`; shipping_options/free da 400 sin item_id
ni dimensions; ninguna respuesta de MeLi trae cabeceras de rate limit.
"""
from datetime import datetime, timedelta, timezone

import pytest

import calculadora_costos
import catalogo_ganar
import enriquecimiento
import envio_gratis
import meli_http
import ventas_sync

PREFERENCIAS_REALES = {
    "mandatory_settings": {"currency_id": "ARS", "mode": "me2", "price_limit": 0},
    "free_configurations": [{"condition": {"value": None, "type": "all"}, "rule": {"default": True, "free_mode": "country", "value": None}}],
}


class Resp:
    def __init__(self, estado=200, cuerpo=None, cabeceras=None):
        self.status_code, self._cuerpo, self.headers, self.text = estado, cuerpo, cabeceras or {}, str(cuerpo)

    def json(self):
        return self._cuerpo


@pytest.fixture(autouse=True)
def _sin_pausa(monkeypatch):
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)


# ── 1. Envío gratis: lo informa Mercado Libre ──────────────────────────────────────────────────────────────────────────────────────────────
def test_las_preferencias_reales_no_inventan_un_piso():
    i = envio_gratis.interpretar_preferencias(PREFERENCIAS_REALES)
    assert i == {"umbral_obligatorio": None, "vendedor_ofrece_gratis_siempre": True}
    assert envio_gratis.es_obligatorio(50000, i) is None                                  # sin piso informado no se afirma nada


def test_el_piso_sale_de_price_limit_y_cambia_con_lo_que_informa_mercado_libre():
    for piso in (33000, 45000.5):
        i = envio_gratis.interpretar_preferencias({"mandatory_settings": {"price_limit": piso}})
        assert i["umbral_obligatorio"] == piso
        assert envio_gratis.es_obligatorio(piso, i) is True and envio_gratis.es_obligatorio(piso - 1, i) is False
    assert envio_gratis.interpretar_preferencias(None) == {"umbral_obligatorio": None, "vendedor_ofrece_gratis_siempre": False}
    assert envio_gratis.interpretar_preferencias({"mandatory_settings": {"price_limit": "x"}})["umbral_obligatorio"] is None


def test_una_publicacion_dice_si_su_envio_gratis_es_obligatorio():
    assert envio_gratis.de_publicacion({"free_shipping": True, "tags": ["self_service_in", "mandatory_free_shipping"]}) == {"gratis": True, "obligatorio": True}
    assert envio_gratis.de_publicacion({"free_shipping": False, "tags": []}) == {"gratis": False, "obligatorio": False}
    assert envio_gratis.de_publicacion(None) == {"gratis": False, "obligatorio": False}


def test_sin_item_ni_medidas_no_se_pide_el_envio_y_se_explica_por_que(monkeypatch):
    monkeypatch.setattr(meli_http, "get", lambda *a, **k: pytest.fail("MeLi responde 400 sin item_id ni dimensions: no hay que preguntarle"))
    costo, obligatorio, motivo = envio_gratis.costo_para_vendedor({}, 1, 20000)
    assert costo is None and obligatorio is None and "peso y las medidas" in motivo
    assert envio_gratis.costo_para_vendedor({}, 1, 20000, dimensiones="10 x 10")[2]          # medidas mal escritas tampoco


def test_con_la_publicacion_o_las_medidas_se_pide_el_envio_con_lo_que_exige_mercado_libre(monkeypatch):
    pedidos = []
    monkeypatch.setattr(meli_http, "get", lambda url, **k: pedidos.append((url, k["params"])) or Resp(200, {"coverage": {"all_country": {"list_cost": 8290}}}))
    assert envio_gratis.costo_para_vendedor({}, 7, 20000, item_id="MLA1856324771")[0] == 8290
    assert pedidos[-1][1]["item_id"] == "MLA1856324771" and "dimensions" not in pedidos[-1][1]
    assert envio_gratis.costo_para_vendedor({}, 7, 20000, dimensiones="10x20x30,500")[0] == 8290
    assert pedidos[-1][1]["dimensions"] == "10x20x30,500" and "item_id" not in pedidos[-1][1] and pedidos[-1][0].endswith("/users/7/shipping_options/free")


def test_la_dimension_invalida_se_rechaza_antes_de_llegar_a_mercado_libre():
    ok = ("10x20x30,500", "1x1x1,1", "100x100x100,999999")
    mal = ("10x20x30", "10 x 20 x 30, 500", "axbxc,5", "10x20x30,500; DROP", "1000x1x1,1", "")
    assert all(envio_gratis.DIMENSIONES_VALIDAS.match(d) for d in ok) and not any(envio_gratis.DIMENSIONES_VALIDAS.match(d) for d in mal)


def test_el_desglose_trae_el_piso_y_el_motivo_cuando_falta_el_paquete(monkeypatch):
    def get(url, **k):
        if url.endswith("/listing_prices"):
            return Resp(200, [{"listing_type_id": "gold_special", "sale_fee_amount": 3000, "sale_fee_details": {"meli_percentage_fee": 15}}])
        if url.endswith("/users/me"):
            return Resp(200, {"id": 7})
        if url.endswith("/shipping_preferences"):
            return Resp(200, {"mandatory_settings": {"price_limit": 33000}})
        pytest.fail(f"no debería pedir {url}")
    monkeypatch.setattr(meli_http, "get", get)
    d = calculadora_costos.calcular_desglose_real("tok", 40000, "MLA1055", "gold_special", False)
    assert d["envio_gratis_desde"] == 33000 and d["envio_obligatorio_gratis"] is True and d["costo_envio"] is None and "medidas" in d["envio_motivo"]
    assert d["recibis"] == 37000                                                         # sin costo de envío conocido no se inventa uno


# ── 2. Comisión: ya sale de listing_prices en vivo ─────────────────────────────────────────────────────────────────────────────────────────
def test_la_comision_de_la_calculadora_sale_de_listing_prices_y_no_de_un_porcentaje_fijo():
    pedidos = []

    def get(url, **k):
        pedidos.append((url, k.get("params")))
        if url.endswith("/listing_prices"):
            return Resp(200, {"listing_type_id": "gold_special", "sale_fee_amount": 4321.5, "sale_fee_details": {"meli_percentage_fee": 13.5, "fixed_fee": 0}})
        return Resp(404, {})
    import unittest.mock as mock
    with mock.patch.object(meli_http, "get", get):
        d = calculadora_costos.calcular_desglose_real("tok", 32000, "MLA1055", "gold_special", False)
    assert d["comision_total"] == 4321.5 and d["pct_comision_base"] == 13.5
    assert pedidos[0][0] == "https://api.mercadolibre.com/sites/MLA/listing_prices" and pedidos[0][1]["price"] == 32000 and pedidos[0][1]["category_id"] == "MLA1055"


# ── 3. Órdenes canceladas: ventanas de fecha, nunca offset más allá de 1000 ────────────────────────────────────────────────────────────────
def _orden_falsa(total_por_ventana):
    """Mercado Libre de mentira: cada llamada recibe la ventana pedida y devuelve `total_por_ventana(desde, hasta)` resultados (pagina de a 50, rechaza offset > 1000)."""
    llamadas = []

    def get(url, headers=None, params=None, **k):
        desde = datetime.strptime(params["order.date_last_updated.from"][:19], "%Y-%m-%dT%H:%M:%S")
        hasta = datetime.strptime(params["order.date_last_updated.to"][:19], "%Y-%m-%dT%H:%M:%S")
        total = total_por_ventana(desde, hasta)
        llamadas.append((desde, hasta, params["offset"]))
        if params["offset"] + params["limit"] > 1000 + 50:
            return Resp(400, {"message": "offset too high"})
        n = max(0, min(params["limit"], total - params["offset"]))
        base = int(desde.timestamp())
        return Resp(200, {"results": [{"id": f"{base}-{params['offset'] + i}"} for i in range(n)], "paging": {"total": total}})
    return get, llamadas


def test_una_ventana_con_mas_de_mil_canceladas_se_parte_por_fecha_y_no_se_pierde_ninguna(monkeypatch):
    desde = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hasta = desde + timedelta(days=8)
    # 400 por día: 3.200 en total, pero nunca más de 1000 en una ventana de 2 días
    def total(d, h):
        return int(400 * ((h - d).total_seconds() / 86400))
    get, llamadas = _orden_falsa(total)
    monkeypatch.setattr(meli_http, "get", get)
    ids = ventas_sync._ids_ordenes_canceladas("tok", 99, desde, hasta)
    assert ids is not None and len(ids) == 3200
    assert max(o for _, _, o in llamadas) <= ventas_sync.LIMITE_OFFSET_MELI


def test_una_ventana_chica_se_pide_de_una_sola_vez(monkeypatch):
    get, llamadas = _orden_falsa(lambda d, h: 120)
    monkeypatch.setattr(meli_http, "get", get)
    ids = ventas_sync._ids_ordenes_canceladas("tok", 99, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert len(ids) == 120 and [o for _, _, o in llamadas] == [0, 50, 100]


def test_si_mercado_libre_falla_en_un_tramo_no_se_retira_nada(monkeypatch):
    monkeypatch.setattr(meli_http, "get", lambda *a, **k: Resp(500, {}))
    assert ventas_sync._ids_ordenes_canceladas("tok", 99, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)) is None


def test_sin_desde_se_mira_el_historial_acotado_por_fecha(monkeypatch):
    visto = {}

    def get(url, headers=None, params=None, **k):
        visto.setdefault("desde", params["order.date_last_updated.from"])
        return Resp(200, {"results": [], "paging": {"total": 0}})
    monkeypatch.setattr(meli_http, "get", get)
    assert ventas_sync._ids_ordenes_canceladas("tok", 99) == []
    assert visto["desde"].startswith(str((datetime.now(timezone.utc) - timedelta(days=ventas_sync.DIAS_HISTORIAL_CANCELADAS)).year))


# ── 4. Catálogo: detalle completo en JSONB, el número no rompe ─────────────────────────────────────────────────────────────────────────────
def test_el_precio_para_ganar_se_extrae_aunque_mercado_libre_lo_mande_como_objeto():
    assert enriquecimiento.precio_para_ganar(25990.5) == 25990.5 and enriquecimiento.precio_para_ganar("100") == 100.0
    assert enriquecimiento.precio_para_ganar({"price": 21000, "free_shipping": True}) == 21000.0
    assert enriquecimiento.precio_para_ganar({"amount": 19000}) == 19000.0
    assert enriquecimiento.precio_para_ganar({"otra": 1}) is None and enriquecimiento.precio_para_ganar(None) is None
    assert enriquecimiento.precio_para_ganar(True) is None and enriquecimiento.precio_para_ganar("x") is None


def test_el_detalle_guarda_solo_lo_que_se_usa_incluidas_las_condiciones():
    d = {"item_id": "MLA1", "price_to_win": 23000, "status": "competing", "visit_share": "medium", "competitors_sharing_first_place": 2,
         "boosts": [{"id": "free_shipping", "status": "opportunity", "description": "Envío gratis"}],
         "winner": {"item_id": "MLA9", "price": 22000, "boosts": [{"id": "free_shipping"}], "seller_id": 123456}}
    detalle = enriquecimiento.detalle_catalogo(d)
    assert detalle["boosts"][0]["id"] == "free_shipping" and detalle["winner"] == {"price": 22000, "boosts": [{"id": "free_shipping"}]}
    assert "item_id" not in detalle and "seller_id" not in str(detalle)                      # nada de otros vendedores
    assert enriquecimiento.detalle_catalogo({}) == {}


def test_las_condiciones_del_ganador_llegan_a_la_pantalla_de_catalogo():
    detalle = {"boosts": [{"id": "free_shipping", "status": "opportunity", "description": "Envío gratis"}, "basura"]}
    assert catalogo_ganar.condiciones_del_ganador(detalle) == [{"id": "free_shipping", "estado": "opportunity", "descripcion": "Envío gratis"}]
    assert catalogo_ganar.condiciones_del_ganador(None) == [] and catalogo_ganar.condiciones_del_ganador({"boosts": None}) == []


def test_la_migracion_agrega_la_columna_jsonb_sin_tocar_la_numerica():
    import os
    sql = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations", "0039_catalogo_detalle.sql"), encoding="utf-8").read()
    assert "ADD COLUMN IF NOT EXISTS catalogo_detalle JSONB" in sql and "DROP" not in sql.upper() and "ALTER COLUMN" not in sql.upper()


# ── 5. Freno por cabeceras de rate limit ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_sin_cabeceras_de_limite_no_hay_pausa_como_en_las_respuestas_reales():
    assert meli_http.espera_segun_cabeceras(200, {"Content-Type": "application/json", "Date": "x"}) == 0
    assert meli_http.espera_segun_cabeceras(200, None) == 0
    meli_http.frenar_segun_cabeceras(Resp(200, {}))
    assert meli_http._pausa["hasta"] == 0.0


def test_con_poco_cupo_restante_se_espera_hasta_que_se_renueve():
    assert meli_http.espera_segun_cabeceras(200, {"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "7"}) == 7
    assert meli_http.espera_segun_cabeceras(200, {"x-rate-limit-remaining": "2", "x-rate-limit-reset": "3"}) == 3
    assert meli_http.espera_segun_cabeceras(200, {"X-RateLimit-Remaining": "500", "X-RateLimit-Reset": "7"}) == 0       # con cupo de sobra no se frena
    assert meli_http.espera_segun_cabeceras(200, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "999"}) == meli_http.PAUSA_TRAS_RECHAZO  # tope


def test_un_429_o_503_con_retry_after_frena_y_sin_el_usa_la_pausa_por_defecto():
    assert meli_http.espera_segun_cabeceras(429, {"Retry-After": "4"}) == 4
    assert meli_http.espera_segun_cabeceras(503, {"Retry-After": "2"}) == 2
    assert meli_http.espera_segun_cabeceras(429, {}) == meli_http.PAUSA_TRAS_RECHAZO
    assert meli_http.espera_segun_cabeceras(500, {"Retry-After": "5"}) == 0


def test_el_reinicio_como_hora_epoch_se_convierte_en_segundos_que_faltan():
    import time
    espera = meli_http.espera_segun_cabeceras(200, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 6)})
    assert 4 <= espera <= 7


def test_la_pausa_es_para_todos_los_pedidos_siguientes_incluido_el_wrapper_de_tokens(monkeypatch):
    meli_http.frenar_segun_cabeceras(Resp(200, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "5"}))
    assert meli_http._pausa["hasta"] > 0
    esperas = []
    monkeypatch.setattr(meli_http.time, "sleep", lambda s: esperas.append(s))
    monkeypatch.setattr(meli_http._sesion, "get", lambda url, **k: Resp(200, {}))
    meli_http.get("https://api.mercadolibre.com/items/1")
    assert len(esperas) == 1 and 0 < esperas[0] <= 5

    from auth import token_manager as tm
    monkeypatch.setattr(tm, "asegurar_token_valido", lambda cuenta_id: "tok")
    monkeypatch.setattr(tm.requests, "request", lambda *a, **k: Resp(200, {}))
    meli_http.frenar_segun_cabeceras(Resp(200, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "5"}))
    esperas.clear()
    tm.llamar_api_meli(1, "GET", "https://api.mercadolibre.com/items/1")
    assert len(esperas) == 1                                                                 # el wrapper de tokens también respeta la pausa

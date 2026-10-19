"""
Flex automático: los anillos de precio que se detectan de lo que Mercado Libre informa de cada envío, la bonificación por cuenta y los envíos que no le cuestan nada a la persona.
Números hechos a mano con los valores reales de la cuenta del dueño: anillos de $4.990 / $6.990 / $8.990 con 10 % de bonificación (costos de $4.491 / $6.291 / $8.091).
"""
import json
import os

import pytest

import flex

ZONAS = [{"id": i, "nombre": n} for i, n in (("Berazategui", "Berazategui"), ("Quilmes", "Quilmes"), ("CABA", "CABA"), ("La_Matanza_1", "La Matanza 1"), ("La_Matanza_2", "La Matanza 2"), ("Almirante_Brown", "Almirante Brown"))]


def _e(familia, costo, tasa=0.1):
    return {"familia": familia, "costo": costo, "tasa": tasa}


# ── La bonificación de la cuenta ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_bonificacion_es_la_de_la_cuenta_o_el_10_por_ciento_de_siempre():
    assert flex.reintegro_de(None) == 0.10 and flex.reintegro_de({}) == 0.10 and flex.reintegro_de({"reintegro": 0.15}) == 0.15 and flex.reintegro_de({"reintegro": 0}) == 0.0
    for raro in ("abc", None, -0.1, 0.9, 5):
        assert flex.reintegro_de({"reintegro": raro}) == 0.10, raro                                       # un dato fuera de 0–50 % no se usa
    assert flex.neto(8990) == 8091.0 and flex.neto(8990, 0.15) == 7641.5 and flex.neto(8990, 0.0) == 8990.0


class _Cursor:
    def __init__(self):
        self.escrituras = []

    def execute(self, sql, params=None):
        self.escrituras.append(params)


def test_la_bonificacion_se_guarda_como_fraccion_y_se_valida():
    c = _Cursor()
    assert flex.guardar_reintegro(c, 7, "15") == (True, None) and c.escrituras == [(0.15, 7)]
    assert flex.guardar_reintegro(c, 7, "12,5") == (True, None) and c.escrituras[-1] == (0.125, 7)
    assert flex.guardar_reintegro(c, 7, 0)[0] is True
    antes = len(c.escrituras)
    for malo in ("abc", None, "-1", "51", "", float("nan")):
        ok, error = flex.guardar_reintegro(c, 7, malo)
        assert ok is False and "bonificación" in error, malo
    assert len(c.escrituras) == antes                                                                      # lo inválido no escribe nada


# ── Los anillos que se detectan ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_los_tres_anillos_salen_de_lo_que_informa_mercado_libre_de_cada_envio():
    envios = ([_e("berazategui", 4491)] * 2 + [_e("quilmes", 6291)] * 3 + [_e("caba", 8091)] * 10 + [_e("la matanza", 8091)] * 2 + [_e("la matanza", 6291)]
              + [_e("caba", 0, None)] + [_e(None, 8091)])
    p = flex.armar_propuesta(envios, ZONAS)
    assert [(u["nombre"], u["envios"]) for u in p["umbrales"]] == [("Zonas cercanas", 2), ("Distancia media", 4), ("Zonas lejanas", 13)]            # los grupos salen de 4.491 < 6.291 < 8.091: de menor a mayor costo
    assert all("precio" not in u for u in p["umbrales"]) and "precio_del_resto" not in p and "$" not in json.dumps(p)                                  # NO se propone ningún precio: lo pone la persona
    assert p["umbrales"][0]["zonas"] == ["Berazategui"] and p["umbrales"][1]["zonas"] == ["Quilmes"]
    assert p["umbrales"][2]["zonas"] == ["CABA", "La_Matanza_1", "La_Matanza_2"]                           # La Matanza: sus dos zonas son una familia; tuvo más envíos a $8.990
    assert "Almirante_Brown" not in json.dumps(p["umbrales"])                                              # una zona sin envíos queda en «resto»: no se inventa su precio
    assert p["reintegro_pct"] == 10.0
    assert p["envios_analizados"] == 20 and p["envios_con_costo"] == 19 and p["envios_sin_costo"] == 1 and p["envios_sin_ubicar"] == 1
    assert p["zonas_en_dos_anillos"] == [{"zona": "La Matanza", "reparto": {"6990": 1, "8990": 2}, "quedo_en": 8990}]


def test_la_bonificacion_de_la_cuenta_se_detecta_y_cambia_los_precios():
    p = flex.armar_propuesta([_e("caba", 4250, 0.15)] * 3 + [_e("quilmes", 5950, 0.15)], ZONAS)             # 15 %: 4.250 ÷ 0,85 = 5.000 y 5.950 ÷ 0,85 = 7.000
    assert p["reintegro_pct"] == 15.0 and [u["nombre"] for u in p["umbrales"]] == ["Zonas cercanas", "Zonas lejanas"] and [u["zonas"] for u in p["umbrales"]] == [["CABA"], ["Quilmes"]]


def test_sin_datos_de_bonificacion_se_usa_la_de_la_cuenta():
    p = flex.armar_propuesta([_e("caba", 8091, None)], ZONAS, reintegro_actual=0.10)
    assert p["reintegro_pct"] == 10.0 and p["umbrales"][0]["nombre"] == "Todas tus zonas con costo"
    assert flex.armar_propuesta([_e("caba", 4000, None)], ZONAS, reintegro_actual=0.20)["reintegro_pct"] == 20.0


def test_si_ninguno_tuvo_costo_no_hay_anillos_que_proponer():
    p = flex.armar_propuesta([_e("caba", 0, None)] * 4, ZONAS)
    assert p["umbrales"] == [] and p["envios_sin_costo"] == 4 and p["envios_con_costo"] == 0


def test_una_zona_con_empate_va_al_anillo_mas_caro_por_prudencia():
    p = flex.armar_propuesta([_e("caba", 4491), _e("caba", 8091), _e("quilmes", 6291)], ZONAS)
    caba = next(u for u in p["umbrales"] if "CABA" in u["zonas"])
    assert caba["nombre"] == "Zonas lejanas"                                                                 # el anillo de 8.091, no el de 4.491


# ── Lo ya consultado a Mercado Libre se guarda y no se repite ───────────────────────────────────────────────────────────────────────────

def test_cada_envio_se_consulta_una_sola_vez_y_sin_token_solo_se_usa_lo_guardado(monkeypatch):
    import cache_db
    memoria, pedidos = {}, []

    def _leer(cursor, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None):
        return (True, dict(memoria)) if memoria else (False, None)

    def _guardar(cursor, cuenta, clave, valor, firma=""):
        memoria.clear()
        memoria.update(valor)
    monkeypatch.setattr(cache_db, "leer", _leer)
    monkeypatch.setattr(cache_db, "guardar", _guardar)
    monkeypatch.setattr(flex, "_costo_de_un_envio", lambda headers, i: pedidos.append(i) or ({"costo": 0.0, "tasa": None} if i == "2" else {"costo": 8091.0, "tasa": 0.1}))
    r = flex.costos_meli(None, 1, "token", [1, "2", 1, None, 3])
    assert sorted(pedidos) == ["1", "2", "3"] and r == {"1": {"costo": 8091.0, "tasa": 0.1}, "2": {"costo": 0.0, "tasa": None}, "3": {"costo": 8091.0, "tasa": 0.1}}
    pedidos.clear()
    assert flex.costos_meli(None, 1, "token", ["2", "3"])["2"]["costo"] == 0.0 and pedidos == []             # ya estaban: no se vuelve a preguntar
    assert flex.costos_meli(None, 1, None, ["4"]) == {} and pedidos == []                                    # un envío nuevo sin token: «no se sabe», no se inventa
    assert flex.costos_meli(None, 1, "token", []) == {}


def test_si_mercado_libre_no_contesta_el_envio_queda_sin_dato_y_no_se_guarda_un_cero(monkeypatch):
    import cache_db
    guardados = []
    monkeypatch.setattr(cache_db, "leer", lambda *a, **k: (False, None))
    monkeypatch.setattr(cache_db, "guardar", lambda cursor, cuenta, clave, valor, firma="": guardados.append(valor))
    monkeypatch.setattr(flex, "_costo_de_un_envio", lambda headers, i: None)
    assert flex.costos_meli(None, 1, "token", ["9"]) == {} and guardados == []


def test_el_costo_de_un_envio_sale_de_senders_y_distingue_cero_de_no_se(monkeypatch):
    class _R:
        def __init__(self, estado, cuerpo):
            self.status_code, self._cuerpo = estado, cuerpo

        def json(self):
            return self._cuerpo
    respuestas = {
        "1": _R(200, {"senders": [{"cost": 8091, "discounts": [{"type": "mandatory", "rate": 0.1}]}]}), "2": _R(200, {"senders": [{"cost": 0, "discounts": []}]}),
        "3": _R(200, {"senders": [{}]}), "4": _R(500, {}), "5": _R(200, {"senders": [{"cost": 4250, "discounts": [{"type": "loyal", "rate": 1}, {"type": "mandatory", "rate": 0.15}]}]}),
    }
    monkeypatch.setattr(flex.meli_http, "get", lambda url, **k: respuestas[url.split("/shipments/")[1].split("/")[0]])
    assert flex._costo_de_un_envio({}, "1") == {"costo": 8091.0, "tasa": 0.1}
    assert flex._costo_de_un_envio({}, "2") == {"costo": 0.0, "tasa": None}                             # $0 informado: no le cuesta nada
    assert flex._costo_de_un_envio({}, "3") is None and flex._costo_de_un_envio({}, "4") is None        # sin dato o con error: no se sabe
    assert flex._costo_de_un_envio({}, "5") == {"costo": 4250.0, "tasa": 0.15}                          # la tasa es la de la bonificación obligatoria, no la del descuento de comprador fiel


# ── Contra la base real: los envíos que no le cuestan nada se resuelven solos ─────────────────────────────────────────────────────────────

class _Revertir(Exception):
    pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_un_envio_que_mercado_libre_informa_en_cero_queda_sin_costo_y_el_resto_se_valua_con_la_bonificacion_de_la_cuenta(monkeypatch):
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario, cuenta = cur.fetchone()
    p = f"AUTO-FLEX-{os.getpid()}"
    umbrales = [{"id": 1, "nombre": None, "precio": 8990, "zonas": [], "resto": True}, {"id": 2, "nombre": "Cerca", "precio": 4990, "zonas": ["Berazategui"], "resto": False}]
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            cur.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb, flex_info = COALESCE(flex_info, '{}'::jsonb) || %s::jsonb WHERE id = %s", (json.dumps(umbrales), json.dumps({"reintegro": 0.15}), cuenta))
            for orden, envio, provincia, localidad, precio in ((f"{p}-A", f"{p}-SA", "Buenos Aires", "Berazategui", 50000), (f"{p}-B", f"{p}-SB", "Capital Federal", "Palermo", 60000),
                                                              (f"{p}-C", f"{p}-SC", "Capital Federal", "Palermo", 8500), (f"{p}-D", f"{p}-SD", "Capital Federal", "Palermo", 70000)):
                cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, cantidad, precio_venta, fecha_venta, origen, tipo_logistica, provincia, localidad, costo_envio, costo_flex, shipment_id)
                               VALUES (%s, %s, 'MLA-AUTO', 1, %s, '2026-09-10', 'meli', 'self_service', %s, %s, 0, 0, %s)""", (cuenta, orden, precio, provincia, localidad, envio))
            informado = {f"{p}-SA": {"costo": 4250.0, "tasa": 0.15}, f"{p}-SB": {"costo": 7641.5, "tasa": 0.15}, f"{p}-SC": {"costo": 0.0, "tasa": None}}      # la D no se pudo consultar
            monkeypatch.setattr(flex, "costos_meli", lambda cursor, cuenta_id, token, ids: informado)
            previa = flex.vista_previa(cur, cuenta, access_token="token")
            assert previa["sin_costo_meli"] >= 1 and previa["ordenes"] >= 4
            flex.aplicar_automatico(cur, cuenta, access_token="token")

            def _fila(orden):
                cur.execute("SELECT flex_zona, flex_zona_meli, costo_flex, costo_envio FROM ventas WHERE cuenta_id = %s AND id_orden = %s", (cuenta, orden))
                z, zm, cf, ce = cur.fetchone()
                return z, zm, float(cf), float(ce)
            assert _fila(f"{p}-A") == (2, "berazategui", 4241.5, 4241.5)             # 4.990 con 15 % de bonificación = 4.241,5 (no con el 10 % de siempre)
            assert _fila(f"{p}-B") == (1, "caba", 7641.5, 7641.5)                    # resto: 8.990 × 0,85
            assert _fila(f"{p}-C") == (0, "*meli", 0.0, 0.0)                         # Mercado Libre informó $0: paga el comprador o lo cubre él; sin costo y sin depender de ningún precio
            assert _fila(f"{p}-D")[0] == 1 and _fila(f"{p}-D")[2] == 7641.5          # sin dato de Mercado Libre: se usa el precio de su zona
            antes = _fila(f"{p}-C")
            flex.aplicar_automatico(cur, cuenta, incluir_valuadas=True, access_token="token")
            assert _fila(f"{p}-C") == antes                                          # recalcular no toca lo que quedó sin costo
            raise _Revertir()
    except _Revertir:
        pass

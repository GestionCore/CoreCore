"""
Cotización del dólar (dolar.py): fuentes con respaldo, dólar MEP automático o manual por cuenta, y lo que se muestra en «Mi cuenta».
Las fuentes se simulan (no sale nada a la red); lo que toca la base corre contra la base real dentro de una transacción que se revierte.
"""
import os
from datetime import date, datetime, timezone

import pytest

import dolar

CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")

DOLARAPI = [
    {"moneda": "USD", "casa": "oficial", "nombre": "Oficial", "compra": 1480, "venta": 1535, "fechaActualizacion": "2030-03-05T13:00:00.000Z"},
    {"moneda": "USD", "casa": "blue", "nombre": "Blue", "compra": 1530, "venta": 1550, "fechaActualizacion": "2030-03-05T13:05:00.000Z"},
    {"moneda": "USD", "casa": "bolsa", "nombre": "Bolsa", "compra": 1520.5, "venta": 1538.4, "fechaActualizacion": "2030-03-05T13:10:00.000Z"},
    {"moneda": "USD", "casa": "cripto", "nombre": "Cripto", "compra": 1, "venta": 2},                     # una casa que no interesa
]
BLUELYTICS = {"oficial": {"value_avg": 1500, "value_sell": 1536, "value_buy": 1490}, "blue": {"value_avg": 1540, "value_sell": 1552, "value_buy": 1528}, "last_update": "2030-03-05T12:00:00-03:00"}


# ── Las fuentes ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_dolarapi_se_lee_casa_por_casa_y_descarta_lo_que_no_sirve():
    r = dolar.parsear_dolarapi(DOLARAPI)
    assert set(r) == {"oficial", "blue", "bolsa"} and r["bolsa"]["venta"] == 1538.4 and r["bolsa"]["compra"] == 1520.5
    assert r["bolsa"]["actualizado"] == datetime(2030, 3, 5, 13, 10, tzinfo=timezone.utc)
    malas = [{"casa": "bolsa", "venta": 0}, {"casa": "blue", "venta": "abc"}, {"casa": "oficial", "venta": None}, {"casa": "bolsa", "venta": -5}, None, {"venta": 100}]
    assert dolar.parsear_dolarapi(malas) == {} and dolar.parsear_dolarapi("no es una lista") == {} and dolar.parsear_dolarapi(None) == {}


def test_bluelytics_solo_da_oficial_y_blue_nunca_el_mep():
    r = dolar.parsear_bluelytics(BLUELYTICS)
    assert set(r) == {"oficial", "blue"} and r["blue"]["venta"] == 1552.0 and "bolsa" not in r
    assert dolar.parsear_bluelytics({"oficial": {"value_sell": 0}}) == {} and dolar.parsear_bluelytics([]) == {}


def _fuentes(dolarapi=None, bluelytics=None):
    def get(url):
        resultado = dolarapi if url == dolar.URL_DOLARAPI else bluelytics
        if isinstance(resultado, Exception):
            raise resultado
        return resultado
    return get


def test_con_dolarapi_no_se_consulta_el_respaldo():
    llamadas = []

    def get(url):
        llamadas.append(url)
        return DOLARAPI
    cot, errores = dolar.traer_cotizaciones(get)
    assert set(cot) == {"oficial", "blue", "bolsa"} and all(c["fuente"] == "dolarapi" for c in cot.values()) and errores == [] and llamadas == [dolar.URL_DOLARAPI]


def test_si_dolarapi_cae_el_respaldo_completa_oficial_y_blue_pero_el_mep_queda_sin_dato():
    cot, errores = dolar.traer_cotizaciones(_fuentes(dolarapi=TimeoutError("sin respuesta"), bluelytics=BLUELYTICS))
    assert set(cot) == {"oficial", "blue"} and cot["blue"]["fuente"] == "bluelytics" and "bolsa" not in cot               # el MEP no se inventa con otra casa
    assert len(errores) == 1 and "dolarapi" in errores[0] and "TimeoutError" in errores[0]


def test_si_dolarapi_trae_solo_algunas_casas_el_respaldo_completa_las_que_faltan():
    solo_mep = [f for f in DOLARAPI if f["casa"] == "bolsa"]
    cot, errores = dolar.traer_cotizaciones(_fuentes(dolarapi=solo_mep, bluelytics=BLUELYTICS))
    assert cot["bolsa"]["fuente"] == "dolarapi" and cot["oficial"]["fuente"] == "bluelytics" and errores == []


def test_si_no_responde_ninguna_fuente_no_se_levanta_nada_y_se_anotan_los_dos_errores():
    cot, errores = dolar.traer_cotizaciones(_fuentes(dolarapi=ConnectionError("x"), bluelytics=ValueError("y")))
    assert cot == {} and len(errores) == 2


# ── El dólar manual ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_dolar_manual_entiende_el_formato_argentino_y_rechaza_lo_que_seria_un_error_de_tipeo():
    esperado = {"1480": 1480.0, "1.480": 1480.0, "1480,5": 1480.5, "1.480,50": 1480.5, "$ 1.500": 1500.0, "10": 10.0, "999999": 999999.0}
    for texto, valor in esperado.items():
        assert dolar.normalizar_manual(texto) == valor, texto
    for malo in ("1.48", "9", "0", "-5", "abc", "", None, "1000000", "2.000.000", "nan", "inf"):
        assert dolar.normalizar_manual(malo) is None, malo                  # «1.48» es un punto de miles que faltó: se rechaza antes que guardar un dólar de $1,48


# ── Contra la base real ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Revertir(Exception):
    pass


def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


@pytest.mark.db
@CON_BASE
def test_guardar_actualiza_el_dia_y_la_cotizacion_activa_prefiere_el_manual_y_si_no_el_mep():
    import db
    usuario, cuenta = _cuenta()
    hoy = date(2030, 3, 7)
    try:
        with db.conexion_admin() as conexion:                       # la tabla es global y solo la escribe el administrador (el scheduler); todo se revierte
            cur = conexion.cursor()
            cot, _ = dolar.traer_cotizaciones(_fuentes(dolarapi=DOLARAPI))
            assert dolar.guardar_cotizaciones(cur, date(2030, 3, 6), cot) == 3
            assert dolar.guardar_cotizaciones(cur, date(2030, 3, 6), cot) == 3                                       # repetir el mismo día actualiza, no duplica
            cur.execute("SELECT COUNT(*) FROM cotizaciones_dolar WHERE fecha = %s", (date(2030, 3, 6),))
            assert cur.fetchone()[0] == 3
            # un valor nuevo del mismo día lo pisa (la tarea corre varias veces por día)
            dolar.guardar_cotizaciones(cur, date(2030, 3, 6), {"bolsa": {"compra": 1, "venta": 1600.0, "actualizado": datetime(2030, 3, 6, 15, 0, tzinfo=timezone.utc), "fuente": "dolarapi"}})
            mep = dolar.ultimo_mep(cur, hoy)
            assert mep["valor"] == 1600.0 and mep["fecha"] == date(2030, 3, 6) and mep["fuente"] == "dolarapi" and mep["desactualizado"] is False

            cur.execute("UPDATE cuentas_meli SET dolar_manual = NULL WHERE id = %s", (cuenta,))
            auto = dolar.cotizacion_activa(cur, cuenta, hoy)
            assert (auto["modo"], auto["valor"], auto["manual"]) == ("automatico", 1600.0, None)                   # sin dólar manual, el MEP
            assert dolar.guardar_modo(cur, cuenta, "manual", "1.480,50") == (True, "Guardamos tu dólar manual.")
            man = dolar.cotizacion_activa(cur, cuenta, hoy)
            assert (man["modo"], man["valor"], man["manual"], man["mep"]["valor"]) == ("manual", 1480.5, 1480.5, 1600.0)       # con dólar manual, ese (y se sigue sabiendo el MEP)
            assert dolar.guardar_modo(cur, cuenta, "manual", "1.48")[0] is False and dolar.guardar_modo(cur, cuenta, "manual", "")[0] is False
            assert dolar.cotizacion_activa(cur, cuenta, hoy)["manual"] == 1480.5                                    # un valor inválido no cambia nada
            assert dolar.guardar_modo(cur, cuenta, "algo raro")[0] is False
            assert dolar.guardar_modo(cur, cuenta, "automatico")[0] is True and dolar.cotizacion_activa(cur, cuenta, hoy)["modo"] == "automatico"
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_un_mep_viejo_se_marca_desactualizado_y_sin_ninguna_cotizacion_el_valor_es_none():
    import db
    usuario, cuenta = _cuenta()
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("DELETE FROM cotizaciones_dolar WHERE casa = 'bolsa'")                   # (revertido al final) para probar el caso «todavía no hay ninguna»
            cur.execute("UPDATE cuentas_meli SET dolar_manual = NULL WHERE id = %s", (cuenta,))
            sin = dolar.cotizacion_activa(cur, cuenta, date(2030, 3, 10))
            assert sin["valor"] is None and sin["mep"] is None and sin["modo"] == "automatico"      # nunca un número supuesto
            antes = datetime(2030, 3, 1, 15, 0, tzinfo=timezone.utc)
            dolar.guardar_cotizaciones(cur, date(2030, 3, 1), {"bolsa": {"compra": 1, "venta": 1500.0, "actualizado": antes, "fuente": "dolarapi"}})
            viejo = dolar.ultimo_mep(cur, date(2030, 3, 10))
            assert viejo["dias"] == 9 and viejo["desactualizado"] is True
            assert dolar.ultimo_mep(cur, date(2030, 3, 4))["desactualizado"] is False              # 3 días: un fin de semana largo, todavía vale
            pantalla = dolar.para_pantalla(dolar.cotizacion_activa(cur, cuenta, date(2030, 3, 10)))
            assert pantalla["valor"] == 1500.0 and pantalla["mep"]["desactualizado"] is True and pantalla["mep"]["actualizado"] and pantalla["mep"]["fuente"] == "dolarapi"
            raise _Revertir()
    except _Revertir:
        pass


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma al salir: lo que escribe la ruta se revierte al final de la prueba."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


@pytest.mark.db
@CON_BASE
def test_mi_cuenta_muestra_el_dolar_y_la_ruta_guarda_el_modo(monkeypatch):
    import app as a
    import db
    usuario, cuenta = _cuenta()
    auditadas = []
    monkeypatch.setattr(a.auditoria, "registrar", lambda accion, detalle=None, **k: auditadas.append(accion))
    cliente = a.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario, cuenta
    post = lambda cuerpo: cliente.post("/api/cuenta/dolar", json=cuerpo, headers={"Sec-Fetch-Site": "same-origin"})
    assert post({"modo": "manual", "valor": "1.48"}).status_code == 400 and post({"modo": "raro"}).status_code == 400 and post({}).status_code == 400      # nada se escribe
    html = cliente.get("/cuenta").get_data(as_text=True)
    assert 'id="dolar"' in html and 'data-modo="automatico"' in html and 'data-modo="manual"' in html and 'id="btn-guardar-dolar"' in html and 'id="input-dolar-manual"' in html
    assert 'type="text" id="input-dolar-manual"' in html and "function parsearDolar" in html                    # texto, no número: «1.480» (punto de miles) no se puede perder en un campo numérico
    try:
        with db.conexion_admin() as conexion:
            monkeypatch.setattr(a.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            dolar.guardar_cotizaciones(cur, date(2030, 3, 6), {"bolsa": {"compra": 1, "venta": 1600.0, "actualizado": None, "fuente": "dolarapi"}})
            d = post({"modo": "manual", "valor": "1.480"}).get_json()
            assert d["ok"] is True and d["dolar"]["modo"] == "manual" and d["dolar"]["valor"] == 1480.0
            d = post({"modo": "automatico"}).get_json()
            assert d["ok"] is True and d["dolar"]["modo"] == "automatico" and d["dolar"]["manual"] is None and d["dolar"]["valor"] is not None
            assert auditadas == ["dolar_cambiar", "dolar_cambiar"]                                                 # solo lo que salió bien queda en la actividad
            raise _Revertir()
    except _Revertir:
        pass

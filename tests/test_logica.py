import time
import cobros
import mensajes
import meli_http
from antirrebote import Antirrebote


def test_resumen_de_la_factura_abierta():
    periodos = [{"period": {"date_from": "2026-09-09", "date_to": "2026-10-08"}, "amount": 1000.0, "unpaid_amount": 250.0, "period_status": "OPEN"}]
    r = cobros.resumen_factura(periodos)
    assert r["descontado"] == 750.0 and r["pct_descontado"] == 75 and r["desde"] == "09/09/2026" and r["deuda_cerrada"] is None


def test_deuda_de_un_periodo_cerrado_se_avisa_con_su_vencimiento():
    periodos = [
        {"period": {"date_from": "2026-09-09", "date_to": "2026-10-08"}, "amount": 100.0, "unpaid_amount": 0.0, "period_status": "OPEN"},
        {"period": {"date_from": "2026-08-09", "date_to": "2026-09-08"}, "amount": 50.0, "unpaid_amount": 20.0, "period_status": "CLOSED", "expiration_date": "2026-09-14"},
    ]
    d = cobros.resumen_factura(periodos)["deuda_cerrada"]
    assert d["monto"] == 20.0 and d["vence"] == "14/09/2026"
    assert cobros.resumen_factura([]) is None


class _Respuesta:
    def __init__(self, codigo, datos):
        self.status_code, self._d = codigo, datos

    def json(self):
        return self._d


def test_mensajes_sin_leer_lee_ordenes_y_packs(monkeypatch):
    datos = {"total": 3, "results": [{"resource": "/orders/2000018730870370", "count": 2}, {"resource": "/packs/2000015290361207/sellers/619292584", "count": 1}, {"resource": "raro"}]}
    monkeypatch.setattr(meli_http, "get", lambda *a, **k: _Respuesta(200, datos))
    r = mensajes.sin_leer("token")
    assert r["total"] == 3 and [c["id"] for c in r["conversaciones"]] == ["2000018730870370", "2000015290361207"]


def test_mensajes_sin_leer_si_mercado_libre_no_responde(monkeypatch):
    monkeypatch.setattr(meli_http, "get", lambda *a, **k: _Respuesta(403, {}))
    assert mensajes.sin_leer("token") is None

    def falla(*a, **k):
        raise RuntimeError("red")
    monkeypatch.setattr(meli_http, "get", falla)
    assert mensajes.sin_leer("token") is None


def test_antirrebote_junta_la_rafaga_en_una_corrida_diferida():
    corridas = []
    ar = Antirrebote(0.3)
    for i in range(10):
        ar.ejecutar((1, "ventas"), lambda i=i: corridas.append(i))
    ar.ejecutar((2, "ventas"), lambda: corridas.append("otra cuenta"))
    assert corridas == [0, "otra cuenta"]           # una inmediata por cuenta
    time.sleep(0.6)
    assert corridas == [0, "otra cuenta", 1]        # las otras 9 se juntan en UNA diferida


def test_antirrebote_nunca_levanta_una_excepcion():
    def malo():
        raise RuntimeError("falla")
    assert Antirrebote(0.1).ejecutar((1, "x"), malo) is True

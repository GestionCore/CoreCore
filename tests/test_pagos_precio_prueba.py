"""
El precio de prueba del cobro real: UN mail paga un monto chico para probar Mercado Pago sin gastar $40.000; nadie más lo ve y sin las variables no cambia nada.
"""
import pagos


def _entorno(monkeypatch, mail=None, precio=None):
    for nombre, valor in (("MP_EMAIL_DE_PRUEBA", mail), ("MP_PRECIO_DE_PRUEBA", precio)):
        if valor is None:
            monkeypatch.delenv(nombre, raising=False)
        else:
            monkeypatch.setenv(nombre, valor)


def test_sin_configurar_todos_pagan_el_precio_del_plan(monkeypatch):
    _entorno(monkeypatch)
    assert pagos.precio_para("base", "alguien@gmail.com") == 40000 and pagos.precio_para("elite", "alguien@gmail.com") == 99000


def test_solo_el_mail_de_prueba_paga_el_monto_chico(monkeypatch):
    _entorno(monkeypatch, "Prueba@Gmail.com", "100")
    assert pagos.precio_para("base", "prueba@gmail.com") == 100 and pagos.precio_para("elite", " PRUEBA@gmail.com ") == 100
    assert pagos.precio_para("base", "otra@gmail.com") == 40000 and pagos.precio_para("base", None) == 40000          # cualquier otra persona, el precio real


def test_una_configuracion_incompleta_o_peligrosa_no_cambia_ningun_precio(monkeypatch):
    for mail, precio in (("prueba@gmail.com", None), (None, "100"), ("prueba@gmail.com", "0"), ("prueba@gmail.com", "-5"), ("prueba@gmail.com", "abc"), ("prueba@gmail.com", "2001"), ("prueba@gmail.com", "")):
        _entorno(monkeypatch, mail, precio)
        assert pagos.precio_para("base", "prueba@gmail.com") == 40000, (mail, precio)                                 # sin las dos variables válidas, o con un monto fuera de rango, rige el precio real


def test_el_link_de_pago_pide_a_mercado_pago_el_monto_correspondiente(monkeypatch):
    enviados = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"init_point": "https://mp/x", "id": "pre1"}
    monkeypatch.setattr(pagos.requests, "post", lambda url, json=None, **k: enviados.append(json) or _Resp())
    _entorno(monkeypatch, "prueba@gmail.com", "100")
    pagos.crear_link_suscripcion("base", 5, "prueba@gmail.com", "https://corelux.app/suscripcion/retorno")
    pagos.crear_link_suscripcion("base", 6, "cliente@gmail.com", "https://corelux.app/suscripcion/retorno")
    assert [e["auto_recurring"]["transaction_amount"] for e in enviados] == [100, 40000]

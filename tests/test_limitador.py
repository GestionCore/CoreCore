import pytest

import limitador


@pytest.fixture(autouse=True)
def _limpio():
    limitador.reiniciar()
    yield
    limitador.reiniciar()


def _pedir(n, ruta="/api/chat_ia", metodo="POST", usuario=1, ip="1.1.1.1", desde=1000.0):
    return [limitador.revisar(ruta, metodo, usuario, ip, ahora=desde + i * 0.01) for i in range(n)]


def test_la_ia_corta_al_pasar_el_maximo_y_avisa_cuanto_esperar():
    resultados = _pedir(25)
    assert resultados[:20] == [None] * 20
    assert all(r and 1 <= r <= 61 for r in resultados[20:])


def test_se_libera_cuando_pasa_la_ventana():
    _pedir(25)
    assert limitador.revisar("/api/chat_ia", "POST", 1, "1.1.1.1", ahora=1000 + 61) is None


def test_el_limite_es_por_usuario_no_global():
    _pedir(25, usuario=1)
    assert limitador.revisar("/api/chat_ia", "POST", 2, "1.1.1.1", ahora=1000.5) is None


def test_sin_sesion_cuenta_por_ip():
    _pedir(25, ruta="/conectar", metodo="GET", usuario=None, ip="9.9.9.9")
    assert limitador.revisar("/conectar", "GET", None, "9.9.9.9", ahora=1000.5)
    assert limitador.revisar("/conectar", "GET", None, "8.8.8.8", ahora=1000.5) is None


def test_la_regla_de_sync_solo_cuenta_los_post():
    assert all(r is None for r in _pedir(10, ruta="/sincronizar_todo", metodo="GET"))
    assert any(_pedir(10, ruta="/sincronizar_todo", metodo="POST", desde=2000.0))


def test_estaticos_webhooks_y_healthcheck_no_se_limitan():
    for ruta in ("/static/css/ux.css", "/notificaciones_meli", "/healthz", "/healthz/db", "/webhook/mercadopago"):
        assert all(r is None for r in _pedir(700, ruta=ruta, usuario=None))


def test_una_ruta_parecida_no_cae_en_la_regla():
    # "/api/chat_ia_otra" no es "/api/chat_ia": solo aplica el límite general
    assert all(r is None for r in _pedir(30, ruta="/api/chat_ia_otra"))


def test_el_limite_general_por_ip_corta_el_abuso():
    resultados = _pedir(650, ruta="/stock", metodo="GET", usuario=None)
    assert resultados[599] is None and resultados[600]

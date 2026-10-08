"""
Errores de fase de la sincronización → Sentry (monitoreo.reportar). Con el SDK real de Sentry y un transporte falso (no sale nada a la red): etiquetas de fase y cuenta, agrupación por fase + tipo de error,
tope de un reporte cada 10 minutos por cuenta, y nunca una excepción ni un dato de más.
"""
import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

import monitoreo


class _Transporte(Transport):
    """Recibe lo que el SDK mandaría a Sentry y lo guarda: no sale nada a la red."""

    def __init__(self, eventos):
        super().__init__()
        self.eventos = eventos

    def capture_envelope(self, envelope):
        evento = envelope.get_event()
        if evento:
            self.eventos.append(evento)


@pytest.fixture
def sentry():
    eventos = []
    sentry_sdk.init(dsn="https://clave@o0.ingest.sentry.io/1", transport=_Transporte(eventos), default_integrations=False, auto_enabling_integrations=False)
    monitoreo._ultimos.clear()
    yield eventos
    sentry_sdk.get_client().close()
    sentry_sdk.init()                      # vuelve a «sin Sentry»
    monitoreo._ultimos.clear()


def test_sin_sentry_configurado_no_hace_nada_y_no_falla():
    sentry_sdk.init()
    assert monitoreo.reportar("ventas", RuntimeError("x"), 7) is False


def test_un_fallo_de_fase_llega_con_fase_y_cuenta_y_sin_datos_de_mas(sentry):
    try:
        raise ConnectionError("Mercado Libre no contestó")
    except ConnectionError as e:
        assert monitoreo.reportar("ventas", e, 7) is True
    sentry_sdk.flush()
    [evento] = sentry
    assert evento["tags"] == {"fase": "ventas", "cuenta_id": "7"}
    assert evento["fingerprint"] == ["sincronizacion", "ventas", "ConnectionError"]       # un solo problema por fase y tipo de error, no uno por cuenta
    assert evento["exception"]["values"][0]["type"] == "ConnectionError"
    assert "user" not in evento or not evento["user"]


def test_el_mismo_fallo_de_la_misma_cuenta_no_se_repite_en_diez_minutos(sentry):
    e = TimeoutError("lento")
    assert monitoreo.reportar("reclamos", e, 7, ahora=1000.0) is True
    assert monitoreo.reportar("reclamos", e, 7, ahora=1000.0 + monitoreo.SEGUNDOS_ENTRE_REPORTES - 1) is False
    assert monitoreo.reportar("reclamos", e, 2, ahora=1010.0) is True                       # otra cuenta: se reporta
    assert monitoreo.reportar("preguntas", e, 7, ahora=1010.0) is True                       # otra fase: se reporta
    assert monitoreo.reportar("reclamos", ValueError("otro"), 7, ahora=1010.0) is True      # otro tipo de error: se reporta
    assert monitoreo.reportar("reclamos", e, 7, ahora=1000.0 + monitoreo.SEGUNDOS_ENTRE_REPORTES + 1) is True   # pasado el tope, vuelve a avisar


def test_reportar_nunca_levanta_una_excepcion(monkeypatch):
    def roto():
        raise RuntimeError("el SDK se rompió")
    monkeypatch.setattr(sentry_sdk, "get_client", roto)
    assert monitoreo.reportar("ventas", ValueError("x"), 1) is False


def test_las_fases_de_sincronizacion_estan_conectadas():
    """Cada paso que se traga un error por cuenta lo reporta (si se quita el aviso, esta prueba lo nota)."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    esperado = {"sincronizador.py": ['"catalogo"', '"ventas"', '"capacidades"', 'f"webhook:{topic}"'], "devoluciones_sync.py": ['"reclamos"', '"preguntas"'],
                "enriquecimiento.py": ['f"enriquecimiento:{nombre}"'], "ventas_sync.py": ['"ventas:envios_viejos"', '"ventas:pagos_viejos"', '"ventas:flex"', '"ventas:canceladas"', '"ventas:financiacion_vieja"']}
    for archivo, fases in esperado.items():
        texto = (raiz / archivo).read_text(encoding="utf-8")
        for fase in fases:
            assert f"monitoreo.reportar({fase}" in texto, (archivo, fase)

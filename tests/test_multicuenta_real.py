"""
Varias cuentas de Mercado Libre de una misma persona (plan Elite), contra la base real dentro de una transacción que nunca se confirma:
  · el botón «Agregar otra cuenta» (menú y Preferencias) desaparece cuando ya están las que permite el plan, y el servidor también lo frena;
  · el botón «Cambiar a esta cuenta» de Preferencias apunta a una ruta que existe (antes hacía POST a /cambiar_cuenta, que no existe: daba 404);
  · el chat del asistente no contesta con la cuenta equivocada si la cuenta activa cambió en otra pestaña.
"""
import os
import re

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con varias cuentas", allow_module_level=True)

import config  # noqa: E402
from auth import registro  # noqa: E402
from tests.test_cuenta_nueva import _Compartida, aplicacion, cliente_nuevo  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


def _agregar_cuenta(nombre, sufijo):
    """Otra cuenta de Mercado Libre para la persona de la prueba (misma transacción, nada queda en la base)."""
    cur = _Compartida.conexion.cursor()
    cur.execute("INSERT INTO cuentas_meli (usuario_id, meli_user_id, nickname, site_id, sincronizacion_inicial_completa, activa) VALUES (%s, %s, %s, 'MLA', true, true) RETURNING id",
                (_Compartida.usuario, 9_100_000_000 + (os.getpid() % 1_000_000) * 10 + sufijo, nombre))
    return cur.fetchone()[0]


def _plan(plan):
    _Compartida.conexion.cursor().execute("UPDATE usuarios SET plan = %s WHERE id = %s", (plan, _Compartida.usuario))


@pytest.fixture
def con_dos_cuentas(cliente_nuevo):  # noqa: F811
    segunda = _agregar_cuenta("SEGUNDA_PRUEBA", 1)
    _plan("elite")
    cliente_nuevo.segunda_cuenta, cliente_nuevo.primera_cuenta = segunda, _Compartida.cuenta
    return cliente_nuevo


# ── Agregar otra cuenta ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_con_una_sola_cuenta_se_ofrece_agregar_otra(cliente_nuevo):  # noqa: F811
    html = cliente_nuevo.get("/cuenta").get_data(as_text=True)
    assert 'href="/conectar_otra_cuenta"' in html and "Agregar otra cuenta" in html


def test_con_las_cuentas_que_permite_el_plan_ya_no_se_ofrece_agregar_otra(con_dos_cuentas):
    assert config.MAX_CUENTAS_ELITE == 2
    for ruta in ("/cuenta", "/dashboard"):
        html = con_dos_cuentas.get(ruta).get_data(as_text=True)
        assert 'href="/conectar_otra_cuenta"' not in html, f"{ruta} sigue ofreciendo agregar una cuenta"
    html = con_dos_cuentas.get("/cuenta").get_data(as_text=True)
    assert "Ya tenés conectadas las 2 cuentas de Mercado Libre que incluye el Plan Elite." in html


def test_el_servidor_tambien_frena_una_tercera_cuenta(con_dos_cuentas):
    r = con_dos_cuentas.get("/conectar_otra_cuenta")
    assert r.status_code == 302 and r.headers["Location"].startswith("/cuenta?msg=")
    assert "las+2+cuentas" in r.headers["Location"]                                                        # el aviso dice cuántas incluye el plan


def test_con_lugar_el_enlace_para_agregar_otra_cuenta_se_arma(cliente_nuevo):  # noqa: F811
    _plan("elite")
    r = cliente_nuevo.get("/conectar_otra_cuenta")
    assert r.status_code == 200 and "mercadolibre" in r.get_data(as_text=True).lower()


def test_vincular_una_cuenta_nueva_sin_lugar_no_crea_nada_y_con_lugar_si(cliente_nuevo):  # noqa: F811
    usuario = _Compartida.usuario
    meli_id = 9_200_000_000 + (os.getpid() % 1_000_000)
    cuenta, resultado = registro.vincular_cuenta_adicional(usuario, {"meli_user_id": meli_id, "nickname": "SEGUNDA_REAL", "site_id": "MLA"})
    assert resultado == "vinculada" and cuenta                                                             # había lugar: la segunda entra
    cuenta, resultado = registro.vincular_cuenta_adicional(usuario, {"meli_user_id": meli_id + 1, "nickname": "TERCERA_REAL", "site_id": "MLA"})
    assert (cuenta, resultado) == (None, "limite")                                                         # ya están las dos: la tercera no se crea
    cur = _Compartida.conexion.cursor()
    cur.execute("SELECT count(*) FROM cuentas_meli WHERE usuario_id = %s", (usuario,))
    assert cur.fetchone()[0] == config.MAX_CUENTAS_ELITE


def test_un_tope_mas_alto_deja_vincular_mas_cuentas(cliente_nuevo, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "MAX_CUENTAS_ELITE", 3)
    usuario = _Compartida.usuario
    base = 9_300_000_000 + (os.getpid() % 1_000_000) * 10
    resultados = [registro.vincular_cuenta_adicional(usuario, {"meli_user_id": base + i, "nickname": f"EXTRA_{i}"})[1] for i in range(3)]
    assert resultados == ["vinculada", "vinculada", "limite"]                                                # la primera ya existía: entran 2 más hasta llegar a 3


# ── Cambiar de cuenta ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_boton_de_cambiar_de_cuenta_de_preferencias_apunta_a_una_ruta_que_existe(con_dos_cuentas):
    html = con_dos_cuentas.get("/cuenta").get_data(as_text=True)
    assert "Estás en esta cuenta" in html and "la que estás viendo" not in html
    acciones = re.findall(r'<form method="POST" action="([^"]+)"[^>]*><button type="submit" class="btn btn-secondary">Cambiar a esta cuenta</button>', html)
    assert acciones == [f"/cambiar_cuenta/{con_dos_cuentas.segunda_cuenta}"]
    r = con_dos_cuentas.post(acciones[0])
    assert r.status_code == 302, f"el botón daba {r.status_code}"
    with con_dos_cuentas.session_transaction() as s:
        assert s["cuenta_id"] == con_dos_cuentas.segunda_cuenta


def test_no_se_puede_cambiar_a_la_cuenta_de_otra_persona(con_dos_cuentas):
    import db
    with db.conexion_admin() as conexion:                                                                   # con la conexión de la persona no se ven las cuentas ajenas (RLS): se busca como administrador
        cur = conexion.cursor()
        cur.execute("SELECT id FROM cuentas_meli WHERE usuario_id <> %s LIMIT 1", (_Compartida.usuario,))
        ajena = cur.fetchone()
    if not ajena:
        pytest.skip("No hay cuentas de otras personas en esta base")
    con_dos_cuentas.post(f"/cambiar_cuenta/{ajena[0]}")
    with con_dos_cuentas.session_transaction() as s:
        assert s["cuenta_id"] == con_dos_cuentas.primera_cuenta


# ── El chat sigue a la cuenta activa ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_chat_no_contesta_con_la_cuenta_equivocada(con_dos_cuentas, monkeypatch):
    llamadas = []

    def responder(usuario_id, pregunta, cuenta_id, historial=None, ruta_actual=None):
        llamadas.append(cuenta_id)
        return {"respuesta": "listo", "botones": []}
    monkeypatch.setattr(aplicacion.chat_ia, "responder_pregunta", responder)
    primera, segunda = con_dos_cuentas.primera_cuenta, con_dos_cuentas.segunda_cuenta
    con_dos_cuentas.post(f"/cambiar_cuenta/{segunda}")                                                      # la persona pasó a la segunda cuenta

    # una pestaña que quedó abierta con la primera cuenta: se frena, no se contesta con datos de otra cuenta
    r = con_dos_cuentas.post("/api/chat_ia", json={"pregunta": "¿cómo vendí?", "cuenta": primera})
    assert r.status_code == 409 and r.get_json()["recargar"] is True and "Recargá" in r.get_json()["respuesta"]
    assert llamadas == []

    # la pestaña de la cuenta activa contesta, y lo hace con ESA cuenta
    r = con_dos_cuentas.post("/api/chat_ia", json={"pregunta": "¿cómo vendí?", "cuenta": segunda})
    assert r.status_code == 200 and r.get_json()["respuesta"] == "listo" and llamadas == [segunda]

    # un navegador viejo que no manda la cuenta sigue andando (se usa la de la sesión)
    r = con_dos_cuentas.post("/api/chat_ia", json={"pregunta": "¿cómo vendí?"})
    assert r.status_code == 200 and llamadas == [segunda, segunda]

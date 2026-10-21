"""Las páginas públicas (planes, términos…) no tienen sesión: no deben consultar las APIs que exigen login (devolvían la página de login y llenaban la consola de errores)."""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_la_pagina_publica_no_marca_el_cuerpo_como_logueado_y_la_privada_si():
    import app as modulo_app
    cliente = modulo_app.app.test_client()
    publica = cliente.get("/planes").get_data(as_text=True)
    assert "<body" in publica and "data-logueado" not in publica
    with cliente.session_transaction() as sesion:
        sesion["usuario_id"] = 987654321                        # un usuario que no existe: /planes lo tolera y solo importa la marca
    con_sesion = cliente.get("/planes").get_data(as_text=True)
    assert 'data-logueado="1"' in con_sesion


def test_el_arranque_solo_consulta_las_apis_con_sesion():
    src = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    arranque = src[src.index("// ---------- Arranque global ----------"):]
    assert "const logueado = !!document.body.dataset.logueado;" in arranque
    # cada consulta periódica o inicial a la API va protegida
    for llamada in ("actualizarTicker();", "marcarVariantesClaveAgotadas();", "cargarOportunidadesSeo();"):
        assert re.search(rf"if \(logueado\) {re.escape(llamada)}", arranque), llamada
    bloque = arranque[arranque.index("if (logueado) {"):]
    assert "cargarAlertasPendientes();" in bloque and "setInterval" in bloque


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_planes_con_sesion_muestra_la_cuenta_de_la_persona_y_no_mi_cuenta():
    """/planes es pública (no pasa por login_requerido): antes la barra decía «Mi cuenta» con la inicial «M» aunque hubiera sesión, y el menú se armaba sin las capacidades de la cuenta."""
    import app as modulo_app
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id, COALESCE(nombre_negocio, nickname) FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario, cuenta, nombre = cur.fetchone()
    cliente = modulo_app.app.test_client()
    with cliente.session_transaction() as sesion:
        sesion["usuario_id"], sesion["cuenta_id"] = usuario, cuenta
    html = cliente.get("/planes").get_data(as_text=True)
    m = re.search(r'<span class="cuenta-inicial">(.)</span><span class="cuenta-nombre">([^<]*)</span>', html)
    assert m, "la barra no muestra la cuenta"
    assert m.group(2).lower() == nombre.lower() and m.group(1) == nombre[0].upper()
    # sin sesión no se muestra ninguna cuenta (y la página no consulta la base)
    anonimo = modulo_app.app.test_client().get("/planes").get_data(as_text=True)
    assert 'class="cuenta-nombre"' not in anonimo or "Mi Cuenta" in anonimo

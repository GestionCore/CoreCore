"""Las páginas públicas (planes, términos…) no tienen sesión: no deben consultar las APIs que exigen login (devolvían la página de login y llenaban la consola de errores)."""
import os
import re

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
    for llamada in ("actualizarTicker();", "marcarCurvaRota();", "cargarOportunidadesSeo();"):
        assert re.search(rf"if \(logueado\) {re.escape(llamada)}", arranque), llamada
    bloque = arranque[arranque.index("if (logueado) {"):]
    assert "cargarAlertasPendientes();" in bloque and "setInterval" in bloque

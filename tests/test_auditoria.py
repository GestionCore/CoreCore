import flask

import auditoria


def _resp(cuerpo, codigo=200):
    app = flask.Flask(__name__)
    with app.app_context():
        return flask.jsonify(cuerpo), codigo


def test_una_respuesta_ok_se_registra():
    assert auditoria._salio_bien(_resp({"ok": True}))[0]
    assert auditoria._salio_bien(flask.Response("listo", 200))[0]
    assert auditoria._salio_bien(flask.Response("", 302))[0]            # redirect después de guardar un formulario


def test_un_fallo_no_se_registra():
    assert not auditoria._salio_bien(_resp({"ok": False, "error": "x"}))[0]
    assert not auditoria._salio_bien(_resp({"ok": True}, 500))[0]
    assert not auditoria._salio_bien(({"ok": False}, 200))[0]
    assert not auditoria._salio_bien(flask.Response("no", 403))[0]


def test_se_tachan_los_secretos_aunque_esten_anidados():
    pedido = {"precio": 10, "access_token": "abc", "cuentas": [{"clave": "x", "nombre": "n"}], "Authorization": "Bearer z"}
    limpio = auditoria._sin_secretos(pedido)
    assert limpio["access_token"] == "***" and limpio["Authorization"] == "***"
    assert limpio["cuentas"][0] == {"clave": "***", "nombre": "n"}
    assert limpio["precio"] == 10


def test_todas_las_acciones_del_codigo_tienen_etiqueta():
    import re
    usadas = set()
    for archivo in ("app.py", "costos_importar.py"):
        usadas |= set(re.findall(r'@auditar\("([a-z_]+)"\)', open(archivo, encoding="utf-8").read()))
    assert usadas and usadas <= set(auditoria.ETIQUETAS)

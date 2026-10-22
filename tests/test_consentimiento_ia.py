"""
Consentimiento para las funciones con IA (2026-10-22, migración 0052).

Enviar datos de la cuenta a un proveedor externo de IA solo se hace si la persona lo aceptó. El control está en el SERVIDOR: las cinco rutas que llaman a la IA contestan 403 mientras no
haya aceptado, y las pantallas reciben un texto que entienden (cada una lee una clave distinta) y un botón a Mi cuenta. Sin aceptar nunca se llama al proveedor.
"""
import os
import re

import pytest

import consentimiento_ia

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


RUTAS_CON_IA = (
    ("/api/chat_ia", "POST", {"pregunta": "hola"}),
    ("/api/costos_chat", "POST", {"historial": [{"role": "user", "content": "alquiler 100000"}]}),
    ("/api/logros/coach", "GET", None),
    ("/api/drawer/optimizar_titulo/MLA1", "POST", {"titulo": "Buzo azul"}),
    ("/api/preguntas/sugerir", "POST", {"texto": "¿Hay talle XL?"}),
)


def test_la_migracion_es_aditiva_e_idempotente():
    sql = re.sub(r"--.*$", "", _leer("migrations", "0052_ia_consentimiento.sql"), flags=re.M)
    assert re.search(r"ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ia_consentimiento_en TIMESTAMPTZ", sql)
    assert not re.search(r"\bDROP\b|\bDEFAULT\b", sql, re.I), "nadie queda aceptado por defecto"


def test_toda_ruta_que_llama_a_la_ia_exige_el_consentimiento():
    """Si se agrega una ruta nueva que llama al proveedor sin el decorador, esta prueba la encuentra: lista las funciones que llaman a ia_asistente / alcance_ia / chat_ia."""
    app_py = _leer("app.py")
    for ruta, _, _ in RUTAS_CON_IA:
        patron = re.escape(ruta.split("/MLA1")[0]).replace("/api/drawer/optimizar_titulo", "/api/drawer/optimizar_titulo/<id_meli>")
        bloque = re.search(r'@app\.route\("' + patron + r'[^"]*"[^\n]*\n((?:@[^\n]*\n)+)def ', app_py)
        assert bloque, ruta
        assert "@consentimiento_ia.requerido" in bloque.group(1), f"{ruta} llama a la IA sin pedir el consentimiento"
        assert bloque.group(1).index("@login_requerido") < bloque.group(1).index("@consentimiento_ia.requerido"), "el decorador va DEBAJO de login_requerido"


def _persona_de_la_base():
    """Una persona real de la base que pase el onboarding y la sincronización inicial (login_requerido lo exige): se usa su sesión, no se escribe nada."""
    import db
    with db.conexion_admin() as conexion:
        cur = conexion.cursor()
        cur.execute("""SELECT c.usuario_id, c.id FROM cuentas_meli c JOIN usuarios u ON u.id = c.usuario_id
                       WHERE u.onboarding_completo AND c.sincronizacion_inicial_completa ORDER BY c.id LIMIT 1""")
        return cur.fetchone()


@pytest.fixture
def cliente(monkeypatch):
    import app as aplicacion
    import ia_asistente
    persona = _persona_de_la_base()
    if not persona:
        pytest.skip("Hace falta una persona con la cuenta lista en la base")
    monkeypatch.setattr(aplicacion.consentimiento_ia, "tiene", lambda usuario_id: False)
    for nombre in ("preguntar_ia", "completar_con_herramientas"):                  # si algo llegara al proveedor, la prueba falla
        if hasattr(ia_asistente, nombre):
            monkeypatch.setattr(ia_asistente, nombre, lambda *a, **k: pytest.fail("se llamó al proveedor de IA sin consentimiento"))
    c = aplicacion.app.test_client()
    with c.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = persona
    return c


@CON_BASE
@pytest.mark.parametrize("ruta,metodo,cuerpo", RUTAS_CON_IA)
def test_sin_aceptar_las_cinco_rutas_contestan_403_y_no_llaman_al_proveedor(cliente, ruta, metodo, cuerpo):
    r = cliente.open(ruta, method=metodo, json=cuerpo, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 403, (ruta, r.status_code)
    d = r.get_json()
    assert d["sin_consentimiento_ia"] is True
    for clave in ("error", "detalle", "mensaje", "respuesta"):
        assert "Mi cuenta" in d[clave], clave                     # cada pantalla lee una clave distinta
    assert d["accion"] == "error" and d["ok"] is False
    assert d["botones"] == [{"texto": "Activar la IA en Mi cuenta", "url": "/cuenta#ia"}]


def test_el_texto_de_la_respuesta_no_promete_ni_asusta():
    t = consentimiento_ia.MENSAJE_SIN_CONSENTIMIENTO
    assert "desactivadas" in t and "Mi cuenta" in t
    assert "error" not in t.lower() and "no autorizado" not in t.lower()


def test_ante_cualquier_falla_se_asume_que_no_acepto(monkeypatch):
    class Rota:
        def __enter__(self):
            raise RuntimeError("base caída")

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(consentimiento_ia.db, "conexion_usuario", lambda *a, **k: Rota())
    assert consentimiento_ia.tiene(1) is False
    assert consentimiento_ia.guardar(1, True) is False


def test_el_onboarding_y_mi_cuenta_dejan_elegir_y_explican_que_se_envia():
    onboarding = _leer("templates", "onboarding.html")
    assert 'name="usar_ia" value="si"' in onboarding and 'name="usar_ia" value="no"' in onboarding
    assert "servicio externo de IA" in onboarding and "Nunca</b> le enviamos tu contraseña" in onboarding
    assert 'data-paso="5"' in onboarding
    cuenta = _leer("templates", "cuenta.html")
    assert 'id="ia"' in cuenta and 'action="/cuenta/ia"' in cuenta and "servicio externo de IA" in cuenta


def test_el_onboarding_solo_acepta_si_o_no_y_solo_activa_con_si(monkeypatch):
    import onboarding
    guardados = []
    monkeypatch.setattr(onboarding.consentimiento_ia, "guardar", lambda uid, acepta: guardados.append((uid, acepta)) or True)

    class Fingida:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return self

        def execute(self, *a, **k):
            pass
    monkeypatch.setattr(onboarding.db, "conexion_usuario", lambda *a, **k: Fingida())
    base = dict(prioridades=["todo"], experiencia="nuevo", pantalla="dashboard")
    assert onboarding.guardar_respuestas(7, usar_ia="quizás", **base) is False and guardados == []
    assert onboarding.guardar_respuestas(7, usar_ia="no", **base) is True and guardados == []
    assert onboarding.guardar_respuestas(7, **base) is True and guardados == []
    assert onboarding.guardar_respuestas(7, usar_ia="si", **base) is True and guardados == [(7, True)]


@CON_BASE
def test_aceptar_y_retirar_el_consentimiento_contra_la_base_real():
    """Dentro de una transacción que se revierte: sin migración aplicada la columna se crea ahí mismo."""
    import db
    resultado = {}

    class _Revertir(Exception):
        pass
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute(_leer("migrations", "0052_ia_consentimiento.sql"))
            cur.execute(_leer("migrations", "0052_ia_consentimiento.sql"))           # dos veces: idempotente
            cur.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1")
            fila = cur.fetchone()
            if not fila:
                pytest.skip("Hace falta al menos un usuario en la base")
            uid = fila[0]
            cur.execute("UPDATE usuarios SET ia_consentimiento_en = NULL WHERE id = %s", (uid,))

            class _Mantener:
                def __enter__(self_):
                    return con

                def __exit__(self_, *a):
                    return False
            original = consentimiento_ia.db.conexion_usuario
            consentimiento_ia.db.conexion_usuario = lambda *a, **k: _Mantener()
            try:
                resultado["antes"] = consentimiento_ia.tiene(uid)
                assert consentimiento_ia.guardar(uid, True) is True
                resultado["aceptado"] = consentimiento_ia.tiene(uid)
                assert consentimiento_ia.guardar(uid, False) is True
                resultado["retirado"] = consentimiento_ia.tiene(uid)
            finally:
                consentimiento_ia.db.conexion_usuario = original
            raise _Revertir()
    except _Revertir:
        pass
    assert resultado == {"antes": False, "aceptado": True, "retirado": False}

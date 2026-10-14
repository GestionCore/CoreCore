"""
Lo primero que ve un cliente: una cuenta recién conectada, sin ventas, sin publicaciones, sin costos y con Mercado Libre sin contestar. Hasta ahora solo se recorrieron las pantallas con la cuenta del dueño
(llena de datos): un vendedor nuevo es donde aparecen las divisiones por cero, los None sin tratar y los estados vacíos mal armados.

Se crea una cuenta vacía DENTRO de una transacción que nunca se confirma (con el mismo rol y las mismas políticas de aislamiento que usa la app: la prueba no ve nada de nadie más) y se recorren todas las
pantallas y los datos que piden por detrás. Mercado Libre se simula caído (sin red) y el token es falso. Ninguna pantalla puede dar un error 500 ni una excepción.
"""
import os
import re
import traceback

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omite el recorrido con una cuenta nueva", allow_module_level=True)

import app as aplicacion  # noqa: E402
import db  # noqa: E402

OMITIR = ("/static", "/logout", "/callback", "/conectar", "/reconectar", "/webhook", "/healthz", "/csp-report", "/notificaciones_meli", "/exportar", "/descargar", "/api/descargar")
SCRIPT_SIN_NONCE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)(?![^>]*\bnonce=)[^>]*>")


class _Compartida:
    """El reemplazo de db.conexion_usuario: entrega SIEMPRE la misma conexión (la de la cuenta nueva, que no se confirma) con un punto de guardado por bloque, así un error dentro de un `with` no deja
    toda la transacción abortada (en la app real cada bloque tiene su propia conexión)."""
    conexion = None
    usuario = None
    cuenta = None

    def __init__(self, usuario_id, cuenta_id=None):
        self.cuenta_pedida = cuenta_id

    def __enter__(self):
        c = _Compartida.conexion
        cur = c.cursor()
        cur.execute("SAVEPOINT bloque")
        cur.execute("SELECT set_config('app.usuario_actual', %s, true), set_config('app.cuenta_actual', %s, true)", (str(_Compartida.usuario), str(_Compartida.cuenta)))
        return c

    def __exit__(self, tipo, valor, tb):
        cur = _Compartida.conexion.cursor()
        if tipo is None:
            cur.execute("RELEASE SAVEPOINT bloque")
        else:
            cur.execute("ROLLBACK TO SAVEPOINT bloque")
            cur.execute("RELEASE SAVEPOINT bloque")


@pytest.fixture
def cliente_nuevo(monkeypatch):
    import requests

    from auth import registro, token_manager
    pid = os.getpid() % 1_000_000
    conexion = db._obtener_pool().getconn()
    try:
        cur = conexion.cursor()
        cur.execute("INSERT INTO usuarios (email, plan, trial_termina_en, referral_code) VALUES (%s, 'trial', now() + interval '14 days', %s) RETURNING id",
                    (f"nuevo-{pid}@corelux.invalid", registro._generar_referral_code(cur)))
        usuario_id = cur.fetchone()[0]
        cur.execute("SELECT set_config('app.usuario_actual', %s, true), set_config('app.cuenta_actual', '', true)", (str(usuario_id),))
        cur.execute("INSERT INTO cuentas_meli (usuario_id, meli_user_id, nickname, site_id) VALUES (%s, %s, 'CUENTA_NUEVA_PRUEBA', 'MLA') RETURNING id", (usuario_id, 9_000_000_000 + pid))
        cuenta_id = cur.fetchone()[0]
        cur.execute("UPDATE usuarios SET onboarding_completo = true WHERE id = %s", (usuario_id,))
        cur.execute("UPDATE cuentas_meli SET sincronizacion_inicial_completa = true, activa = true WHERE id = %s", (cuenta_id,))
        _Compartida.conexion, _Compartida.usuario, _Compartida.cuenta = conexion, usuario_id, cuenta_id

        monkeypatch.setattr(db, "conexion_usuario", _Compartida)
        monkeypatch.setattr(token_manager, "asegurar_token_valido", lambda cuenta: "token-falso")

        def _sin_red(*a, **k):
            raise requests.exceptions.ConnectionError("sin red (prueba)")
        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _sin_red)

        aplicacion.app.config["TESTING"] = True
        cliente = aplicacion.app.test_client()
        with cliente.session_transaction() as s:
            s["usuario_id"], s["cuenta_id"] = usuario_id, cuenta_id
            s["mostrar_tutorial"] = False
        yield cliente
    finally:
        _Compartida.conexion = None
        conexion.rollback()
        db._obtener_pool().putconn(conexion)


def _rutas_get():
    for rule in sorted(aplicacion.app.url_map.iter_rules(), key=lambda r: r.rule):
        if "GET" not in rule.methods or rule.arguments or rule.rule.startswith(OMITIR):
            continue
        yield rule.rule


def test_ninguna_pantalla_ni_dato_falla_para_un_vendedor_recien_conectado(cliente_nuevo):
    malas, total = [], 0
    for ruta in _rutas_get():
        total += 1
        try:
            r = cliente_nuevo.get(ruta)
        except Exception as e:                                                                        # TESTING = True: una excepción sin atrapar llega hasta acá
            tb = traceback.extract_tb(e.__traceback__)[-1]
            malas.append(f"{ruta} -> {type(e).__name__}: {str(e)[:110]} ({os.path.basename(tb.filename)}:{tb.lineno})")
            continue
        if r.status_code == 500:
            malas.append(f"{ruta} -> 500")
        elif r.status_code == 200 and r.mimetype == "text/html" and SCRIPT_SIN_NONCE.search(r.get_data(as_text=True)):
            malas.append(f"{ruta} -> <script> sin nonce")
    assert total > 40, f"el recorrido casi no encontró pantallas ({total})"
    assert not malas, f"{len(malas)} de {total} fallan con una cuenta nueva:\n" + "\n".join(malas)


def test_la_cuenta_nueva_no_ve_los_datos_de_nadie_mas(cliente_nuevo):
    """Aislamiento de punta a punta: con la cuenta vacía, lo que devuelven los datos del dashboard no tiene ni una venta ni una publicación (las cuentas reales sí tienen)."""
    r = cliente_nuevo.get("/api/hoy")
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert not cuerpo.get("ordenes_hoy") and not cuerpo.get("ultimas_ventas")
    r = cliente_nuevo.get("/api/dashboard/ultimas_ventas")
    assert r.status_code == 200 and r.get_json() == []
    r = cliente_nuevo.get("/api/dashboard/top_productos")
    assert r.status_code == 200 and r.get_json() == []

"""
Ola 3 (D73): «Deshacer» durante 8 segundos para lo que se puede revertir: eliminar un gasto (se oculta, no se pierde; el scheduler lo borra de verdad pasado un día) e ignorar una pregunta.
El aviso con botón es genérico (`mostrarToast(mensaje, tipo, { accion })`): lo probado acá con node es la lógica de verdad; lo probado contra la base real es que NADA se pierde ni se reabre de más.
"""
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN") or not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


class _Revertir(Exception):
    pass


class _Mantener:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


# ── El aviso con botón y el aviso de «Gasto eliminado» (node, sin navegador) ─────────────────────────────────────────────────────────────

def _correr_node(tmp_path, cuerpo):
    js = _leer("static", "js", "global.js").replace("\r\n", "\n")
    toast = js[js.index("const TOASTS_MAXIMOS = 3;"):js.index("function revisarMensajeEnURL()")]
    gasto = js[js.index("// Al borrar un gasto, Costos recarga"):js.index("// ---------- Modo Privacidad ----------")]
    guion = tmp_path / "deshacer.js"
    guion.write_text("function sonidoExito() {}\nfunction sonidoError() {}\n" + toast + "\n" + gasto + "\n" + cuerpo, encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


_DOM_FALSO = """
function crear() {
  const e = { children: [], handlers: {}, className: '', attrs: {}, textContent: '', padre: null,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, f) { this.handlers[t] = f; },
    append(...n) { n.forEach(x => { if (x && typeof x === 'object') x.padre = this; this.children.push(x); }); },
    appendChild(x) { x.padre = this; this.children.push(x); return x; },
    remove() { if (this.padre) this.padre.children = this.padre.children.filter(c => c !== this); },
    get firstElementChild() { return this.children[0]; } };
  return e;
}
const contenedor = crear();
const temporizadores = [];
global.document = { getElementById: () => contenedor, createElement: crear, createTextNode: (t) => ({ texto: t }) };
global.requestAnimationFrame = (f) => f();
global.setTimeout = (f, ms) => { temporizadores.push({ f, ms }); return temporizadores.length; };
global.clearTimeout = () => {};
"""


@CON_NODE
def test_un_aviso_con_deshacer_dura_8_segundos_y_al_apretarlo_se_cierra_y_hace_lo_suyo(tmp_path):
    r = _correr_node(tmp_path, _DOM_FALSO + """
let hechas = 0;
mostrarToast('Pregunta ignorada', 'info', { accion: { texto: 'Deshacer', alHacer: () => { hechas++; } } });
const aviso = contenedor.children[0];
const boton = aviso.children.find(c => c.className === 'toast-accion');
const duracion = temporizadores[temporizadores.length - 1].ms;
boton.handlers.click();
mostrarToast('Listo', 'success');                                                       // un aviso común no lleva botón y dura lo de siempre (entre 4 y 9 s)
const comun = contenedor.children[contenedor.children.length - 1];
console.log(JSON.stringify({ texto: boton.textContent, duracion, hechas, cerrado: !aviso.classList.contains('visible'),
  comunSinBoton: !comun.children.some(c => c.className === 'toast-accion'), duracionComun: temporizadores[temporizadores.length - 1].ms }));
""")
    assert r["texto"] == "Deshacer" and r["duracion"] == 8000 and r["hechas"] == 1 and r["cerrado"]
    assert r["comunSinBoton"] and 4000 <= r["duracionComun"] <= 9000


@CON_NODE
def test_al_volver_de_eliminar_un_gasto_el_aviso_ofrece_deshacer_y_limpia_la_direccion(tmp_path):
    r = _correr_node(tmp_path, _DOM_FALSO + """
const avisos = [], urls = [], pedidos = [];
global.window = { location: { search: '?fecha_desde=2026-10-01&fecha_hasta=2026-10-31&deshacer_gasto=42', hash: '#gastos-negocio', pathname: '/costos', reload() { pedidos.push('recarga'); } }, history: { replaceState: (a, b, u) => urls.push(u) } };
mostrarToast = (m, t, o) => avisos.push({ m, t, o });
global.fetch = async (url, opts) => { pedidos.push(url + ' ' + opts.method); return { ok: true, json: async () => ({ ok: true }) }; };
(async () => {
  avisarGastoEliminado();
  const guardado = avisos[0];
  await guardado.o.accion.alHacer();                                                       // «Deshacer»: pide recuperar ese gasto y recarga la página
  window.location.search = '?deshacer_gasto=abc';                                          // un valor que no es un número no genera nada
  avisarGastoEliminado();
  window.location.search = '?fecha_desde=2026-10-01';                                      // sin el parámetro, tampoco
  avisarGastoEliminado();
  console.log(JSON.stringify({ avisos: avisos.length, mensaje: guardado.m, texto: guardado.o.accion.texto, urls, pedidos }));
})();
""")
    assert r["avisos"] == 1 and r["mensaje"] == "Gasto eliminado" and r["texto"] == "Deshacer"
    assert r["urls"][0] == "/costos?fecha_desde=2026-10-01&fecha_hasta=2026-10-31#gastos-negocio"       # el parámetro sale de la dirección (recargar no repite el aviso) y se conserva la pestaña
    assert r["pedidos"] == ["/restaurar_gasto/42 POST", "recarga"]


@CON_NODE
def test_si_no_se_puede_recuperar_el_gasto_se_avisa_y_no_se_recarga(tmp_path):
    r = _correr_node(tmp_path, _DOM_FALSO + """
const avisos = [], pedidos = [];
global.window = { location: { search: '', pathname: '/costos', reload() { pedidos.push('recarga'); } } };
mostrarToast = (m, t) => avisos.push({ m, t });
global.fetch = async () => ({ ok: false, json: async () => ({ ok: false, detalle: 'Ese gasto ya no se puede recuperar.' }) });
(async () => { await restaurarGasto('7'); console.log(JSON.stringify({ avisos, pedidos })); })();
""")
    assert r["avisos"] == [{"m": "Ese gasto ya no se puede recuperar.", "t": "error"}] and r["pedidos"] == []


# ── Contra la base real ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@contextmanager
def _transaccion(monkeypatch):
    """Una conexión con todo lo que escriban las rutas; al salir se revierte entera. Devuelve (conexión, usuario, cuenta, cliente ya con sesión)."""
    import app as a
    import db
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT usuario_id, id FROM cuentas_meli WHERE activa ORDER BY id LIMIT 1")
            persona = cur.fetchone()
            if not persona:
                pytest.skip("Hace falta una cuenta en la base")
            monkeypatch.setattr(db, "conexion_usuario", lambda *x, **k: _Mantener(con))
            cliente = a.app.test_client()
            with cliente.session_transaction() as s:
                s["usuario_id"], s["cuenta_id"] = persona
            yield con, persona[0], persona[1], cliente
            raise _Revertir()
    except _Revertir:
        pass


def _gasto(cur, cuenta, concepto="Gasto de prueba"):
    cur.execute("INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha) VALUES (%s, %s, 'variable', 1234, '2030-03-10') RETURNING id", (cuenta, concepto))
    return cur.fetchone()[0]


@pytest.mark.db
@CON_BASE
def test_eliminar_un_gasto_lo_oculta_no_lo_borra_y_se_puede_recuperar_durante_un_dia(monkeypatch):
    with _transaccion(monkeypatch) as (con, usuario, cuenta, cliente):
        cur = con.cursor()
        id_gasto = _gasto(cur, cuenta)
        r = cliente.post(f"/eliminar_gasto/{id_gasto}", data={"fecha_desde": "2030-03-01", "fecha_hasta": "2030-03-31"})
        assert r.status_code == 302 and r.headers["Location"] == f"/costos?fecha_desde=2030-03-01&fecha_hasta=2030-03-31&deshacer_gasto={id_gasto}#gastos-negocio"
        cur.execute("SELECT eliminado_en IS NOT NULL FROM gastos_operativos WHERE id = %s", (id_gasto,))
        assert cur.fetchone() == (True,)                                                          # sigue en la base, solo oculto
        # Eliminarlo de nuevo no cambia nada y no ofrece un «Deshacer» de algo que ya no está a la vista
        r2 = cliente.post(f"/eliminar_gasto/{id_gasto}", data={"fecha_desde": "2030-03-01", "fecha_hasta": "2030-03-31"})
        assert "deshacer_gasto" not in r2.headers["Location"]
        # Deshacer: vuelve a estar a la vista
        ok = cliente.post(f"/restaurar_gasto/{id_gasto}")
        assert ok.status_code == 200 and ok.get_json() == {"ok": True}
        cur.execute("SELECT eliminado_en FROM gastos_operativos WHERE id = %s", (id_gasto,))
        assert cur.fetchone() == (None,)
        # Pasado el día el scheduler ya lo borró de verdad: ya no se recupera
        cur.execute("UPDATE gastos_operativos SET eliminado_en = now() - interval '2 days' WHERE id = %s", (id_gasto,))
        viejo = cliente.post(f"/restaurar_gasto/{id_gasto}")
        assert viejo.status_code == 404 and viejo.get_json()["ok"] is False
        assert cliente.post("/restaurar_gasto/987654321").status_code == 404                       # un gasto que no existe


@pytest.mark.db
@CON_BASE
def test_un_gasto_eliminado_no_suma_en_ninguna_pantalla(monkeypatch):
    import costos
    with _transaccion(monkeypatch) as (con, usuario, cuenta, cliente):
        cur = con.cursor()
        a_la_vista, eliminado = _gasto(cur, cuenta, "A la vista"), _gasto(cur, cuenta, "Eliminado")
        cliente.post(f"/eliminar_gasto/{eliminado}", data={"fecha_desde": "2030-03-01", "fecha_hasta": "2030-03-31"})
        gastos, _stats, _productos = costos.obtener_datos_costos(usuario, "2030-03-01", "2030-03-31", cuenta)
        assert [g["id"] for g in gastos if g["concepto"] in ("A la vista", "Eliminado")] == [a_la_vista]       # la pantalla de Costos no lo muestra
        cur.execute("SELECT COALESCE(SUM(monto), 0) FROM gastos_operativos WHERE eliminado_en IS NULL AND cuenta_id = %s AND fecha = '2030-03-10'", (cuenta,))
        assert float(cur.fetchone()[0]) == 1234.0


def _pregunta(cur, cuenta, question_id, estado):
    cur.execute("INSERT INTO preguntas_pendientes (cuenta_id, question_id, item_id, texto_pregunta, estado) VALUES (%s, %s, 'PRUEBA-DESH-1', '¿Hay?', %s)", (cuenta, question_id, estado))


def _estado(cur, cuenta, question_id):
    cur.execute("SELECT estado FROM preguntas_pendientes WHERE cuenta_id = %s AND question_id = %s", (cuenta, question_id))
    return cur.fetchone()[0]


@pytest.mark.db
@CON_BASE
def test_deshacer_ignorar_solo_reabre_lo_que_estaba_ignorado(monkeypatch):
    with _transaccion(monkeypatch) as (con, usuario, cuenta, cliente):
        cur = con.cursor()
        for qid, estado in (("9920000000001", "pendiente"), ("9920000000002", "ignorada"), ("9920000000003", "respondida"), ("9920000000004", "borrada")):
            _pregunta(cur, cuenta, qid, estado)
        assert cliente.post("/api/preguntas/ignorar", json={"question_ids": ["9920000000001"]}).get_json()["ok"] is True
        assert _estado(cur, cuenta, "9920000000001") == "ignorada"
        r = cliente.post("/api/preguntas/restaurar", json={"question_ids": ["9920000000001", "9920000000002", "9920000000003", "9920000000004"]}).get_json()
        assert r == {"ok": True, "restauradas": 2}                                                # solo las dos que estaban ignoradas
        assert [_estado(cur, cuenta, q) for q in ("9920000000001", "9920000000002", "9920000000003", "9920000000004")] == ["pendiente", "pendiente", "respondida", "borrada"]
        assert cliente.post("/api/preguntas/restaurar", json={"question_ids": []}).status_code == 400


# ── Que ninguna pantalla lea gastos que la persona ya eliminó ────────────────────────────────────────────────────────────────────────────

def test_toda_lectura_de_gastos_deja_afuera_los_eliminados():
    sin_filtro = []
    for nombre in sorted(os.listdir(RAIZ)):
        if not nombre.endswith(".py") or nombre in ("flex.py", "scheduler.py", "migrate.py"):          # flex.py lee SUS propios gastos (envíos devueltos); el scheduler es quien los purga
            continue
        texto = _leer(nombre)
        for m in re.finditer(r"FROM gastos_operativos", texto):
            if "eliminado_en" not in texto[m.start():m.start() + 420]:
                sin_filtro.append(nombre)
    assert sin_filtro == []

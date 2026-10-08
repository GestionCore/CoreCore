"""
Fase 2 de la auditoría (concurrencia y sincronización). Ya estaban resueltos y con pruebas propias: 10 (refresco de token con advisory lock por cuenta: tests/test_token_refresco.py),
11 (timeout por defecto de 15 s: la misma) y 12 (UniqueViolation al vincular cuentas: tests/test_correcciones_auditoria.py). Acá: 9, 13, 14 y 15.
"""
import json
import os
import shutil
import subprocess

import pytest

import scheduler
import stock_meli

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


class Resp:
    def __init__(self, estado, cuerpo):
        self.status_code, self._c = estado, cuerpo

    def json(self):
        return self._c


# ── 9. Stock masivo: nunca se escribe a ciegas ─────────────────────────────────────────────────────────────────────────────────────────────
def _obtener(item, estado=200):
    pedidos = []

    def obtener(url, **k):
        pedidos.append(url)
        return Resp(estado, item)
    obtener.pedidos = pedidos
    return obtener


def test_si_el_stock_de_mercado_libre_coincide_con_el_de_la_pantalla_se_puede_escribir():
    obtener = _obtener({"available_quantity": 5})
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "5", obtener) == ("ok", 5)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", [], 5, obtener) == ("ok", 5)                # una publicación sin variantes guardadas
    assert "attributes=available_quantity,variations" in obtener.pedidos[0]


def test_si_cayo_una_venta_mientras_se_editaba_no_se_escribe_y_se_informa_el_stock_actual():
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "5", _obtener({"available_quantity": 4})) == ("cambio", 4)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "5", _obtener({"available_quantity": 9})) == ("cambio", 9)       # también si lo subieron
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "0", _obtener({"available_quantity": 0})) == ("ok", 0)


def test_una_variacion_se_compara_con_su_propio_stock_y_no_con_el_de_la_publicacion():
    item = {"available_quantity": 12, "variations": [{"id": 111, "available_quantity": 7}, {"id": 222, "available_quantity": 5}]}
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["111"], "7", _obtener(item)) == ("ok", 7)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["111"], "12", _obtener(item)) == ("cambio", 7)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["999"], "7", _obtener(item)) == ("no_verificable", None)        # esa variación ya no existe


def test_si_no_se_puede_comparar_no_se_escribe():
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "5", _obtener({}, estado=500)) == ("no_verificable", None)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], None, _obtener({"available_quantity": 5})) == ("no_verificable", None)
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "abc", _obtener({"available_quantity": 5})) == ("no_verificable", None)

    def cae(*a, **k):
        raise RuntimeError("sin red")
    assert stock_meli.verificar_antes_de_escribir({}, "MLA1", ["MLA1_unica"], "5", cae) == ("no_verificable", None)


def test_la_ruta_de_stock_masivo_verifica_antes_de_cada_put_y_avisa_lo_que_no_guardo():
    app = _leer("app.py")
    cuerpo = app[app.index("def actualizar_stock_multiple"):app.index("def despacho_marcar")]
    assert cuerpo.index("stock_meli.verificar_antes_de_escribir(") < cuerpo.index("meli_http.put(")                    # primero se mira, después se escribe
    assert "originales.get(id_meli)" in cuerpo and 'estado_stock == "cambio"' in cuerpo and 'estado_stock == "no_verificable"' in cuerpo
    assert "su stock cambió mientras editabas" in cuerpo and "no pudimos confirmar su stock actual" in cuerpo
    assert "not cambiaron and not sin_verificar" in cuerpo                                                                # un guardado con ítems cortados no es «éxito»


# ── 13. «Sincronizando…» nunca se queda sin salida ────────────────────────────────────────────────────────────────────────────────────────
def test_la_pantalla_de_sincronizacion_ofrece_reintentar_y_salir_cuando_se_traba():
    t = _leer("templates", "sincronizando.html")
    assert 'href="/logout"' in t and t.count("var salir =") == 1 and "reintentar + escribir + salir" in t
    assert "'sin_conexion'" in t and "FALLAS_PARA_AVISAR" in t and "fallasSeguidas = 0" in t                              # si el servidor deja de contestar también avisa
    assert "MINUTOS_MAXIMOS_DE_ESPERA" in t and "pasoDemasiado" in t                                                       # y si pasa mucho tiempo aunque el servidor diga «normal»
    assert 'data-click="reintentarSync"' in t and "/sincronizar_todo" in t
    assert "cada 4 minutos: tus números" not in t


# ── 14. Webhook como motor; el scheduler solo barre ────────────────────────────────────────────────────────────────────────────────────────
def test_la_barredora_es_de_30_minutos_por_defecto_y_se_puede_cambiar_con_un_minimo(monkeypatch):
    monkeypatch.delenv("SYNC_INTERVALO_MINUTOS", raising=False)
    assert scheduler._intervalo_barredora() == 30
    monkeypatch.setenv("SYNC_INTERVALO_MINUTOS", "60")
    assert scheduler._intervalo_barredora() == 60
    monkeypatch.setenv("SYNC_INTERVALO_MINUTOS", "1")
    assert scheduler._intervalo_barredora() == 5                                                                           # nunca por debajo del mínimo
    monkeypatch.setenv("SYNC_INTERVALO_MINUTOS", "mucho")
    assert scheduler._intervalo_barredora() == 30


def test_el_scheduler_ya_no_sincroniza_todo_cada_4_minutos_pero_reintenta_rapido_las_cuentas_nuevas():
    fuente = _leer("scheduler.py")
    assert 'add_job(_tarea_sincronizar_todo, "interval", minutes=_intervalo_barredora(), id="sync_todo"' in fuente
    assert 'add_job(_tarea_sincronizar_cuentas_nuevas, "interval", minutes=INTERVALO_CUENTAS_NUEVAS_MINUTOS, id="sync_cuentas_nuevas"' in fuente
    assert scheduler.INTERVALO_CUENTAS_NUEVAS_MINUTOS == 4 and "minutes=4" not in fuente


def test_el_reintento_rapido_solo_toma_las_cuentas_con_la_primera_sincronizacion_pendiente(monkeypatch):
    consultas = []

    class Cursor:
        def execute(self, sql, params=None):
            consultas.append(sql)

        def fetchall(self):
            return [(1, 10)]

    class Conexion:
        def cursor(self):
            return Cursor()

    from contextlib import contextmanager

    @contextmanager
    def conexion_admin():
        yield Conexion()
    monkeypatch.setattr(scheduler.db, "conexion_admin", conexion_admin)
    scheduler._obtener_cuentas_activas()
    scheduler._obtener_cuentas_activas(solo_sin_sync_inicial=True)
    assert "sincronizacion_inicial_completa" not in consultas[0] and "AND sincronizacion_inicial_completa = false" in consultas[1]

    sincronizadas = []
    monkeypatch.setattr(scheduler, "_obtener_cuentas_activas", lambda solo_sin_sync_inicial=False: [("nueva", 1)] if solo_sin_sync_inicial else [("a", 1), ("b", 2)])
    monkeypatch.setattr(scheduler, "_sincronizar_cuentas", lambda cuentas: sincronizadas.append(list(cuentas)))
    scheduler._tarea_sincronizar_cuentas_nuevas()
    scheduler._tarea_sincronizar_todo()
    assert sincronizadas == [[("nueva", 1)], [("a", 1), ("b", 2)]]


# ── 15. Doble toque en Despacho ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _correr_toggle(escenario, tmp_path):
    t = _leer("templates", "_dia_despacho.html")
    funcion = t[t.index("function toggleDespacho"):t.rindex("</script>")]
    guion = tmp_path / "toggle.js"
    guion.write_text(f"""
{funcion}
const llamadas = [], toasts = [];
function refrescarProgreso() {{}}
function mostrarToast(m) {{ toasts.push(m); }}
const clases = new Set();
const check = {{ textContent: '' }};
const elemento = {{ dataset: {{}}, style: {{}}, classList: {{ contains: c => clases.has(c), toggle: (c, f) => ((f === undefined ? !clases.has(c) : f) ? clases.add(c) : clases.delete(c)) }}, querySelector: () => check }};
let pendiente;
globalThis.fetch = (url, opciones) => {{ llamadas.push(JSON.parse(opciones.body)); return new Promise((res, rej) => {{ pendiente = {{ res, rej }}; }}); }};
const espera = () => new Promise(r => setTimeout(r, 5));
(async () => {{
  const salida = {{}};
  toggleDespacho(elemento, '1', 'MLA1', '');
  toggleDespacho(elemento, '1', 'MLA1', '');            // el segundo toque, con el primero todavía guardándose
  salida.durante = {{ posts: llamadas.length, bloqueada: elemento.style.pointerEvents === 'none', despachado: clases.has('despachado') }};
  {escenario}
  console.log(JSON.stringify(salida));
}})();
""", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_un_segundo_toque_mientras_se_guarda_no_manda_otro_post_y_al_terminar_se_libera(tmp_path):
    r = _correr_toggle("pendiente.res({ ok: true }); await espera(); salida.despues = { bloqueada: elemento.style.pointerEvents === 'none', guardando: elemento.dataset.guardando || null, despachado: clases.has('despachado') };", tmp_path)
    assert r["durante"] == {"posts": 1, "bloqueada": True, "despachado": True}
    assert r["despues"] == {"bloqueada": False, "guardando": None, "despachado": True}


@CON_NODE
def test_si_el_guardado_falla_se_revierte_se_avisa_y_la_tarjeta_vuelve_a_responder(tmp_path):
    r = _correr_toggle("pendiente.res({ ok: false }); await espera(); salida.despues = { bloqueada: elemento.style.pointerEvents === 'none', guardando: elemento.dataset.guardando || null, despachado: clases.has('despachado'), toasts: toasts.length };", tmp_path)
    assert r["despues"] == {"bloqueada": False, "guardando": None, "despachado": False, "toasts": 1}
    r = _correr_toggle("pendiente.rej(new Error('red')); await espera(); salida.despues = { bloqueada: elemento.style.pointerEvents === 'none', despachado: clases.has('despachado'), toasts: toasts.length };", tmp_path)
    assert r["despues"] == {"bloqueada": False, "despachado": False, "toasts": 1}


def test_el_bloqueo_se_levanta_en_un_finally_para_que_nunca_quede_trabada():
    t = _leer("templates", "_dia_despacho.html")
    cuerpo = t[t.index("function toggleDespacho"):]
    assert ".finally(() => {" in cuerpo and "elemento.style.pointerEvents = '';" in cuerpo and "delete elemento.dataset.guardando" in cuerpo

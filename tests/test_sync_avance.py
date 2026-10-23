"""
Avance real de la primera importación (N10): la pantalla de espera dice «1.240 de ~3.000 órdenes» (y muestra una barrita) en vez de solo «1.240». Los totales los informa Mercado Libre al
empezar (cuántas publicaciones tiene la cuenta y cuántas órdenes hay en el último año) y se anotan en la caché compartida; son una estimación, por eso siempre con «~».
"""
import json
import os
import shutil
import subprocess
from contextlib import contextmanager

import pytest

import sync_avance
import ventas_sync

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN") or not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


class _Revertir(Exception):
    pass


class _Mantener:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


# ── Lo que se anota ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@contextmanager
def _transaccion(monkeypatch):
    import db
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT usuario_id, id FROM cuentas_meli WHERE activa ORDER BY id LIMIT 1")
            persona = cur.fetchone()
            if not persona:
                pytest.skip("Hace falta una cuenta en la base")
            cur.execute("DELETE FROM cache_valores WHERE cuenta_id = %s AND clave = %s", (persona[1], sync_avance.CLAVE))
            monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _Mantener(con))
            yield con, persona
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@CON_BASE
def test_los_totales_se_suman_sin_pisar_lo_anotado_y_ignoran_lo_que_no_sirve(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        assert sync_avance.leer(cur, cuenta) == {}
        assert sync_avance.guardar(cur, cuenta, publicaciones=192) == {"publicaciones": 192}
        assert sync_avance.guardar(cur, cuenta, ventas=3000, publicaciones=None) == {"publicaciones": 192, "ventas": 3000}           # lo que ya estaba no se pierde
        assert sync_avance.guardar(cur, cuenta, ventas=0, publicaciones=-5, otra="x", cosa=True) == {"publicaciones": 192, "ventas": 3000}   # cero, negativos, texto y booleanos no son totales
        assert sync_avance.leer(cur, cuenta) == {"publicaciones": 192, "ventas": 3000}


@pytest.mark.db
@CON_BASE
def test_anotar_abre_su_conexion_y_nunca_rompe_la_sincronizacion(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        assert sync_avance.anotar(usuario, cuenta, ventas=1234) == {"ventas": 1234}
        assert sync_avance.leer(con.cursor(), cuenta) == {"ventas": 1234}
    import db

    def _falla(*a, **k):
        raise RuntimeError("la base no responde")
    monkeypatch.setattr(db, "conexion_usuario", _falla)
    assert sync_avance.anotar(1, 1, ventas=99) == {}                                       # un error al anotar se traga: la importación sigue


def test_la_etapa_de_ventas_dura_hasta_que_entra_casi_todo_lo_esperado():
    assert sync_avance.faltan_ordenes(1240, 3000, True) is True                            # entraron 41 %: sigue importando órdenes
    assert sync_avance.faltan_ordenes(2800, 3000, True) is False                           # 93 %: lo que falta son las canceladas, que nunca se guardan
    assert sync_avance.faltan_ordenes(10, 3000, False) is False                            # si la importación no está en curso no se espera nada
    assert sync_avance.faltan_ordenes(10, None, True) is False and sync_avance.faltan_ordenes(10, 0, True) is False       # sin total conocido, como siempre


# ── El total que informa Mercado Libre ───────────────────────────────────────────────────────────────────────────────────────

class _Respuesta:
    def __init__(self, estado, cuerpo):
        self.status_code, self._c = estado, cuerpo

    def json(self):
        return self._c


def test_el_total_de_ordenes_sale_de_un_pedido_de_una_sola_orden(monkeypatch):
    from datetime import datetime, timezone
    pedidos = []

    def _get(url, headers=None, params=None, timeout=None):
        pedidos.append(params)
        return _Respuesta(200, {"results": [{"id": 1}], "paging": {"total": 3017, "limit": 1}})
    monkeypatch.setattr(ventas_sync.meli_http, "get", _get)
    ahora = datetime(2030, 3, 10, tzinfo=timezone.utc)
    assert ventas_sync._total_de_ordenes("token", 99, datetime(2029, 3, 10, tzinfo=timezone.utc), ahora) == 3017
    assert pedidos[0]["limit"] == 1 and pedidos[0]["seller"] == 99                         # un pedido liviano: solo interesa el total


@pytest.mark.parametrize("respuesta", [_Respuesta(500, {}), _Respuesta(200, {"paging": {"total": 0}}), _Respuesta(200, {}), _Respuesta(200, {"paging": {"total": "mucho"}})])
def test_si_no_se_puede_saber_el_total_no_se_inventa_ninguno(monkeypatch, respuesta):
    from datetime import datetime, timezone
    monkeypatch.setattr(ventas_sync.meli_http, "get", lambda *a, **k: respuesta)
    assert ventas_sync._total_de_ordenes("token", 99, datetime(2029, 3, 10, tzinfo=timezone.utc), datetime(2030, 3, 10, tzinfo=timezone.utc)) is None


def test_un_corte_de_red_al_pedir_el_total_no_frena_la_importacion(monkeypatch):
    from datetime import datetime, timezone

    def _get(*a, **k):
        raise ConnectionError("sin red")
    monkeypatch.setattr(ventas_sync.meli_http, "get", _get)
    assert ventas_sync._total_de_ordenes("token", 99, datetime(2029, 3, 10, tzinfo=timezone.utc), datetime(2030, 3, 10, tzinfo=timezone.utc)) is None


def test_solo_la_primera_importacion_pide_el_total_y_el_catalogo_lo_anota():
    fuente = open(os.path.join(RAIZ, "ventas_sync.py"), encoding="utf-8").read()
    primera = fuente[fuente.index("    else:\n        fecha_desde = ahora - timedelta(days=365)"):][:420]
    assert "sync_avance.anotar(usuario_id, cuenta_id, ventas=_total_de_ordenes(" in primera           # dentro del «else» de «no hay última sincronización»
    assert "sync_avance.anotar(usuario_id, cuenta_id, publicaciones=len(lista_ids))" in open(os.path.join(RAIZ, "sincronizador.py"), encoding="utf-8").read()


# ── El endpoint que consulta la pantalla de espera ───────────────────────────────────────────────────────────────────────────

@pytest.mark.db
@CON_BASE
def test_el_estado_de_la_espera_trae_lo_esperado_y_cuenta_ordenes_no_filas(monkeypatch):
    import app as a
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        cur.execute("UPDATE cuentas_meli SET sincronizacion_inicial_completa = false, conectada_en = now() WHERE id = %s", (cuenta,))
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT id_orden) FROM ventas WHERE cuenta_id = %s", (cuenta,))
        filas, ordenes = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %s", (cuenta,))
        productos = cur.fetchone()[0]
        sync_avance.guardar(cur, cuenta, publicaciones=productos + 40, ventas=ordenes * 2 + 10)
        monkeypatch.setattr(a.sincronizador, "sincronizacion_en_curso", lambda cuenta_id: True)
        cliente = a.app.test_client()
        with cliente.session_transaction() as s:
            s["usuario_id"], s["cuenta_id"] = usuario, cuenta
        datos = cliente.get("/api/estado_sincronizacion").get_json()
        assert datos["lista"] is False and datos["en_curso"] is True
        assert datos["productos"] == productos and datos["productos_total"] == productos + 40
        assert datos["ordenes"] == ordenes and datos["ventas"] == filas and datos["ordenes_total"] == ordenes * 2 + 10
        if ordenes and productos:
            assert datos["etapa"] == "ventas"                                                  # entró menos del 90 % de lo esperado: sigue en «órdenes y ventas», no salta a «calculando»
        # sin totales anotados (cuenta que no pasó por la importación nueva) todo sigue como antes
        cur.execute("DELETE FROM cache_valores WHERE cuenta_id = %s AND clave = %s", (cuenta, sync_avance.CLAVE))
        sin = cliente.get("/api/estado_sincronizacion").get_json()
        assert sin["productos_total"] is None and sin["ordenes_total"] is None


# ── La pantalla ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _funciones_js():
    html = open(os.path.join(RAIZ, "templates", "sincronizando.html"), encoding="utf-8").read().replace("\r\n", "\n")
    return html[html.index("function cuantos(n, uno, varios)"):html.index("async function chequearEstado()")]


@CON_NODE
def test_el_texto_y_la_barra_dicen_cuanto_falta_solo_cuando_se_sabe(tmp_path):
    guion = tmp_path / "avance.js"
    guion.write_text(_funciones_js() + """
const cajas = {};
const nodo = (id) => (cajas[id] = cajas[id] || { hidden: true, style: { width: '' } });
global.document = { getElementById: nodo };
const sal = {
  conTotal: textoAvance(1240, 3000, 'orden', 'órdenes'),
  empezando: textoAvance(0, 3000, 'orden', 'órdenes'),
  completo: textoAvance(3000, 3000, 'orden', 'órdenes'),
  pasado: textoAvance(3100, 3000, 'orden', 'órdenes'),
  sinTotal: textoAvance(1240, 0, 'orden', 'órdenes'),
  una: textoAvance(1, 0, 'orden', 'órdenes'),
};
pintarBarra('caja', 'barra', 1240, 3000);
sal.barra = nodo('barra').style.width; sal.barraVisible = !nodo('caja').hidden;
pintarBarra('caja', 'barra', 5000, 3000); sal.tope = nodo('barra').style.width;
pintarBarra('caja', 'barra', 0, 3000); sal.barraSinNada = !nodo('caja').hidden;
pintarBarra('caja', 'barra', 1240, 0); sal.barraSinTotal = !nodo('caja').hidden;
console.log(JSON.stringify(sal));
""", encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:500]
    s = json.loads(r.stdout)
    assert s["conTotal"] == "1.240 de ~3.000 órdenes" and s["empezando"] == "Trayendo ~3.000 órdenes"
    assert s["completo"] == "3000 órdenes" and s["pasado"] == "3100 órdenes" and s["sinTotal"] == "1240 órdenes" and s["una"] == "1 orden"
    assert s["barra"] == "41%" and s["barraVisible"] is True and s["tope"] == "100%"
    assert s["barraSinNada"] is False and s["barraSinTotal"] is False                       # sin nada traído o sin total conocido, no se dibuja una barra que no dice nada

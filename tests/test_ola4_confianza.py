"""
Ola 4 (confianza): lo chico y de mucho efecto de la lista F-P1 del plan maestro.
  · T36  una consulta colgada en un pedido web se corta a los 30 s (statement_timeout, solo en pedidos web);
  · T37  el pool comprueba que la conexión siga viva antes de entregarla;
  · T52  las pantallas y las respuestas con datos de la cuenta no se guardan en el navegador (Cache-Control: private, no-store).
"""
import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── T36: límite de tiempo por consulta, solo en pedidos web ──────────────────────────────────────────────────────────────────────────

def _statement_timeout(db, usuario=999999999):
    with db.conexion_usuario(usuario, None) as conexion:
        cur = conexion.cursor()
        cur.execute("SHOW statement_timeout")
        return cur.fetchone()[0]


@pytest.mark.db
@CON_BASE
def test_en_un_pedido_web_cada_consulta_tiene_tope_y_en_un_hilo_de_fondo_no_se_toca():
    import app as aplicacion
    import db
    fuera = _statement_timeout(db)                                                            # un trabajo de fondo (sincronización, scheduler): lo que ya tenga el rol
    with aplicacion.app.test_request_context("/"):
        dentro = _statement_timeout(db)
    assert dentro == "30s" and fuera != "30s"
    with aplicacion.app.test_request_context("/"):
        assert _statement_timeout(db) == "30s"                                                # y se prepara en cada transacción, no depende de la conexión que le tocó
    assert _statement_timeout(db) == fuera                                                    # nada quedó pegado en la conexión del pool


@pytest.mark.db
@CON_BASE
def test_una_consulta_colgada_se_corta_y_la_conexion_vuelve_al_pool(monkeypatch):
    import psycopg
    import app as aplicacion
    import db
    monkeypatch.setattr(db, "STATEMENT_TIMEOUT_WEB_MS", 300)
    with aplicacion.app.test_request_context("/"):
        with pytest.raises(psycopg.errors.QueryCanceled):
            with db.conexion_usuario(999999999, None) as conexion:
                conexion.cursor().execute("SELECT pg_sleep(5)")
        with db.conexion_usuario(999999999, None) as conexion:                                # la conexión quedó libre y limpia: el pedido siguiente anda
            cur = conexion.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)


@pytest.mark.db
@CON_BASE
def test_se_puede_apagar_el_tope_sin_desplegar(monkeypatch):
    import app as aplicacion
    import db
    monkeypatch.setattr(db, "STATEMENT_TIMEOUT_WEB_MS", 0)
    fuera = _statement_timeout(db)
    with aplicacion.app.test_request_context("/"):
        assert _statement_timeout(db) == fuera


def test_el_valor_por_defecto_sale_de_la_variable_de_entorno():
    fuente = _leer("db.py")
    assert 'STATEMENT_TIMEOUT_WEB_MS = max(0, int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")))' in fuente
    assert 'VERIFICAR_CONEXION = os.getenv("DB_VERIFICAR_CONEXION", "1") != "0"' in fuente


# ── T37: el pool comprueba la conexión antes de entregarla ──────────────────────────────────────────────────────────────────────────

def test_los_dos_pools_se_crean_con_la_comprobacion_de_conexion(monkeypatch):
    import config
    import db
    recibidos = []

    class _PoolFalso:
        check_connection = staticmethod(lambda conexion: None)

        def __init__(self, *args, **kwargs):
            recibidos.append(kwargs)

    monkeypatch.setattr(db, "ConnectionPool", _PoolFalso)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://x", raising=False)
    monkeypatch.setattr(config, "DATABASE_URL_ADMIN", "postgresql://x", raising=False)
    db._crear_pool()
    db._crear_pool_admin()
    assert [k["check"] for k in recibidos] == [_PoolFalso.check_connection] * 2
    monkeypatch.setattr(db, "VERIFICAR_CONEXION", False)
    recibidos.clear()
    db._crear_pool()
    assert recibidos[0]["check"] is None


@pytest.mark.db
@CON_BASE
def test_una_conexion_muerta_no_le_llega_a_un_pedido():
    """Se mata la conexión por dentro (como haría un reinicio del pooler) y el pedido siguiente igual recibe una que anda."""
    import db
    with db.conexion_usuario(999999999, None) as conexion:
        pid = conexion.info.backend_pid
    with db.conexion_admin() as admin:                                                          # otra sesión (la de administración) mata la que quedó en el pool
        cur = admin.cursor()
        cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
    with db.conexion_usuario(999999999, None) as conexion:
        cur = conexion.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


# ── T52: nada con plata queda guardado en el navegador ──────────────────────────────────────────────────────────────────────────────

def test_las_pantallas_y_las_respuestas_de_la_api_no_se_guardan_en_el_navegador():
    import app as aplicacion
    cliente = aplicacion.app.test_client()
    for ruta in ("/healthz", "/", "/ayuda", "/planes"):
        r = cliente.get(ruta)
        assert r.headers.get("Cache-Control") == "private, no-store", ruta


def test_lo_estatico_con_version_sigue_guardandose_un_ano_y_el_resto_de_static_no_se_toca():
    import app as aplicacion
    cliente = aplicacion.app.test_client()
    versionado = cliente.get("/static/css/style.css?v=abc")
    assert versionado.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    sin_version = cliente.get("/static/css/style.css")
    assert "no-store" not in (sin_version.headers.get("Cache-Control") or "")


# ── T50: la imagen no corre como root ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_imagen_corre_con_un_usuario_sin_privilegios_y_lo_que_hay_que_escribir_es_suyo():
    docker = _leer("Dockerfile")
    lineas = [l.strip() for l in docker.splitlines() if l.strip() and not l.strip().startswith("#")]
    comandos = [l.split()[0] for l in lineas]
    assert "USER" in comandos and "USER root" not in lineas
    usuario = next(l for l in lineas if l.startswith("USER "))
    assert usuario == "USER corelux"
    assert lineas.index(usuario) > next(i for i, l in enumerate(lineas) if l.startswith("RUN python verificar_dependencias.py"))        # la comprobación de dependencias corre antes, como administrador
    assert lineas.index(usuario) < next(i for i, l in enumerate(lineas) if l.startswith("CMD "))
    crear = next(i for i, l in enumerate(lineas) if "useradd" in l)
    copiar = next(i for i, l in enumerate(lineas) if l.startswith("COPY --chown=corelux:corelux . ."))
    assert crear < copiar and "chown corelux:corelux /app" in lineas[crear]
    assert "uid 10001" in lineas[crear] and "--system" in lineas[crear]
    assert "EXPOSE 8080" in lineas and 'ENV PORT=8080' in lineas                       # un usuario común no puede abrir puertos por debajo de 1024


def test_nada_de_lo_que_corre_en_produccion_escribe_en_la_carpeta_de_la_app():
    """Con un usuario sin privilegios solo se puede escribir en /tmp y /dev/shm: si alguien agrega una escritura a una ruta relativa, esta prueba lo avisa antes del deploy."""
    sospechosos = []
    for nombre in sorted(os.listdir(RAIZ)):
        if not nombre.endswith(".py") or nombre.startswith(("generar_", "medir_", "normalizar_", "sondeo_", "rotar_", "servir", "respaldo", "migrate", "predeploy", "desplegar", "verificar_", "exportador_")):
            continue
        for numero, linea in enumerate(_leer(nombre).splitlines(), 1):
            if "open(" in linea and any(f"'{m}'" in linea or f'"{m}"' in linea for m in ("w", "wb", "a", "ab", "w+", "x")) and "tmp" not in linea.lower():
                sospechosos.append(f"{nombre}:{numero}")
    assert sospechosos == []


# ── T80: un 429 o un 500 que no llega como JSON no se cuenta como «no se pudo conectar» ────────────────────────────────────────────────

def _correr_node(tmp_path, cuerpo):
    import json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node no está instalado")
    js = _leer("static", "js", "global.js").replace("\r\n", "\n")
    funciones = js[js.index("function mensajeDeEstado(estado)"):js.index("async function guardarDrawerInfo()")]
    guion = tmp_path / "estado.js"
    guion.write_text(funciones + "\n" + cuerpo, encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:500]
    return json.loads(r.stdout)


def test_cada_estado_se_cuenta_con_su_motivo(tmp_path):
    r = _correr_node(tmp_path, """
const falsa = (estado, cuerpo, redirigida = false) => ({ status: estado, redirected: redirigida, json: async () => { if (cuerpo === undefined) throw new Error('no es JSON'); return cuerpo; } });
(async () => {
  const sal = {};
  sal.json = (await leerRespuesta(falsa(200, { ok: true }))).datos;
  sal.m429 = (await leerRespuesta(falsa(429))).mensaje;
  sal.m500 = (await leerRespuesta(falsa(500))).mensaje;
  sal.m504 = (await leerRespuesta(falsa(504))).mensaje;
  sal.sesion = (await leerRespuesta(falsa(200, undefined, true))).mensaje;
  sal.jsonDeError = (await leerRespuesta(falsa(500, { ok: false, detalle: 'x' }))).datos.detalle;
  console.log(JSON.stringify(sal));
})();
""")
    assert r["json"] == {"ok": True} and r["jsonDeError"] == "x"                      # lo que sí es JSON se entrega tal cual: el mensaje del servidor manda
    assert "muchas acciones seguidas" in r["m429"] and "Algo falló de nuestro lado" in r["m500"] and "mucha demanda" in r["m504"] and "sesión terminó" in r["sesion"]
    assert "conectar" not in " ".join([r["m429"], r["m500"], r["m504"], r["sesion"]])


def test_el_panel_de_la_publicacion_usa_el_lector_y_ya_no_inventa_un_problema_de_conexion():
    js = _leer("static", "js", "global.js")
    guardar = js[js.index("async function guardarDrawerInfo()"):][:2600]
    assert "await leerRespuesta(resp)" in guardar and "mostrarToast(leida.mensaje, 'error')" in guardar
    assert "const data = await resp.json();" not in guardar

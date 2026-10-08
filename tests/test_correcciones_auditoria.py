"""
Correcciones de una auditoría de código: código de referido que se valida (y no se confunde con el email), alta y vinculación de cuentas que toleran un doble pedido, racha diaria que
no se pierde con un microcorte, hora de Argentina compartida, limpieza de vínculos OAuth, índices de claves foráneas, workers que no pasan el tope del pooler y capas del CSS.
"""
import os
import re
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from psycopg.errors import UniqueViolation

import db
from auth import registro

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la base real")


def _leer(*ruta):
    return open(os.path.join(RAIZ, *ruta), encoding="utf-8").read()


class _Violacion(UniqueViolation):
    """Una UniqueViolation que dice qué restricción saltó (como la informa Postgres en error.diag.constraint_name)."""

    def __init__(self, restriccion):
        super().__init__()
        self._restriccion = restriccion

    @property
    def diag(self):
        return SimpleNamespace(constraint_name=self._restriccion)


# ── Código de referido ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _CursorCodigos:
    def __init__(self, ocupados):
        self.ocupados, self.consultas, self._ultimo = list(ocupados), [], None

    def execute(self, sql, params=None):
        self.consultas.append(params[0])
        self._ultimo = {"1": 1} if self.ocupados and self.ocupados.pop(0) else None

    def fetchone(self):
        return self._ultimo


def test_el_codigo_de_referido_se_comprueba_en_la_base_y_si_esta_ocupado_se_prueba_otro():
    cursor = _CursorCodigos([True, True, False])                       # los dos primeros ya existen
    codigo = registro._generar_referral_code(cursor)
    assert len(cursor.consultas) == 3 and codigo == cursor.consultas[-1] and len(set(cursor.consultas)) == 3
    assert len(codigo) == 8 and set(codigo) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def test_sin_cursor_devuelve_un_codigo_sin_consultar_nada():
    assert len(registro._generar_referral_code()) == 8


def test_si_todos_los_codigos_estan_ocupados_falla_en_voz_alta():
    with pytest.raises(RuntimeError):
        registro._generar_referral_code(_CursorCodigos([True] * 50))


def test_se_distingue_el_choque_de_codigo_del_choque_de_email():
    assert registro._restriccion_violada(_Violacion("usuarios_referral_code_key")) == "referral_code"
    assert registro._restriccion_violada(_Violacion("usuarios_email_key")) == "email"
    assert registro._restriccion_violada(_Violacion("otra_cosa")) == "otra"
    assert registro._restriccion_violada(ValueError("sin diag")) == "otra"


class _Pool:
    """Pool simulado: cada getconn() entrega una conexión cuyo INSERT en usuarios responde lo que diga el guion (una excepción o un id)."""

    def __init__(self, guion_insert, ocupados_por_codigo=False):
        self.guion, self.inserts, self.commits, self.rollbacks = list(guion_insert), [], 0, 0
        self.ocupados_por_codigo = ocupados_por_codigo
        self.descartados = []

    def getconn(self):
        pool = self

        class Cursor:
            def execute(self, sql, params=None):
                if "FROM usuarios WHERE referral_code" in sql:
                    self.fila = None
                elif sql.startswith("INSERT INTO usuarios"):
                    pool.inserts.append(params)
                    paso = pool.guion.pop(0)
                    if isinstance(paso, Exception):
                        raise paso
                    self.fila = {"id": paso}
                elif sql.startswith("DELETE FROM usuarios"):
                    pool.descartados.append(params[0])

            def fetchone(self):
                return self.fila

        class Conexion:
            def cursor(self, row_factory=None):
                return Cursor()

            def commit(self):
                pool.commits += 1

            def rollback(self):
                pool.rollbacks += 1

        return Conexion()


@contextmanager
def _conexion_falsa(respuestas):
    """conexion_admin / conexion_usuario simuladas: `respuestas` es la lista de lo que devuelve fetchone en orden; un Exception se levanta al ejecutar."""
    pendientes = respuestas

    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            paso = pendientes.pop(0) if pendientes else None
            if isinstance(paso, Exception):
                raise paso
            return paso

    class Conexion:
        def cursor(self, row_factory=None):
            return Cursor()

    yield Conexion()


def _preparar_login(monkeypatch, guion_insert, admin=None, usuario=None):
    pool = _Pool(guion_insert)
    monkeypatch.setattr(db, "_obtener_pool", lambda: pool)
    monkeypatch.setattr(db, "liberar_conexion", lambda c: None)
    admin_respuestas = list(admin if admin is not None else [None])
    monkeypatch.setattr(db, "conexion_admin", lambda: _conexion_falsa(admin_respuestas))
    usuario_respuestas = list(usuario if usuario is not None else [{"id": 77}])
    monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _conexion_falsa(usuario_respuestas))
    return pool


def test_si_choca_el_codigo_de_referido_se_reintenta_con_el_mismo_email_real(monkeypatch):
    pool = _preparar_login(monkeypatch, [_Violacion("usuarios_referral_code_key"), 55])
    usuario_id, cuenta_id, nuevo = registro.crear_o_actualizar_login({"meli_user_id": 1, "nickname": "N"}, "real@correo.com")
    assert (usuario_id, cuenta_id, nuevo) == (55, 77, True)
    emails = [p[0] for p in pool.inserts]
    assert emails == ["real@correo.com", "real@correo.com"]                           # el mismo email dos veces: NO se pasó al provisorio
    assert pool.inserts[0][2] != pool.inserts[1][2]                                   # con otro código
    assert pool.rollbacks == 1 and pool.commits == 1


def test_si_choca_el_email_se_pasa_al_siguiente_candidato(monkeypatch):
    pool = _preparar_login(monkeypatch, [_Violacion("usuarios_email_key"), 56])
    usuario_id, _, _ = registro.crear_o_actualizar_login({"meli_user_id": 9, "nickname": "N"}, "ya_usado@correo.com")
    assert usuario_id == 56
    assert [p[0] for p in pool.inserts] == ["ya_usado@correo.com", registro.email_pendiente(9)]


def test_si_el_codigo_choca_siempre_no_queda_en_un_bucle_ni_se_come_el_email(monkeypatch):
    pool = _preparar_login(monkeypatch, [_Violacion("usuarios_referral_code_key")] * 20 + [1])
    with pytest.raises(RuntimeError):
        registro.crear_o_actualizar_login({"meli_user_id": 1}, "real@correo.com")
    assert len([p for p in pool.inserts if p[0] == "real@correo.com"]) == registro.INTENTOS_CODIGO_REFERIDO


# ── Doble pedido al crear o vincular una cuenta ──────────────────────────────────────────────────────────────────────────────────────────
def test_vincular_con_doble_clic_no_da_error_la_segunda_ve_que_ya_existe(monkeypatch):
    # 1.ª mirada: no existe; el INSERT choca con el UNIQUE (la creó el otro pedido); 2.ª mirada: ya existe y es de este mismo usuario
    monkeypatch.setattr(db, "conexion_admin", lambda c=[None, {"id": 9, "usuario_id": 5}]: _conexion_falsa(c))
    llamadas = []

    @contextmanager
    def usuario(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 1:                                                         # el INSERT
            raise UniqueViolation()
        yield _SoloCursor()                                                            # el UPDATE de «reconectada»
    monkeypatch.setattr(db, "conexion_usuario", usuario)
    assert registro.vincular_cuenta_adicional(5, {"meli_user_id": 123, "nickname": "N"}) == (9, "reconectada")


def test_vincular_con_doble_pedido_y_la_cuenta_es_de_otro_usuario_lo_dice_sin_error(monkeypatch):
    monkeypatch.setattr(db, "conexion_admin", lambda c=[None, {"id": 9, "usuario_id": 99}]: _conexion_falsa(c))

    @contextmanager
    def usuario(*a, **k):
        raise UniqueViolation()
        yield
    monkeypatch.setattr(db, "conexion_usuario", usuario)
    assert registro.vincular_cuenta_adicional(5, {"meli_user_id": 123}) == (None, "ya_de_otro_usuario")


def test_vincular_una_cuenta_nueva_sin_carrera_sigue_dando_vinculada(monkeypatch):
    monkeypatch.setattr(db, "conexion_admin", lambda c=[None]: _conexion_falsa(c))
    monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _conexion_falsa([{"id": 31}]))
    assert registro.vincular_cuenta_adicional(5, {"meli_user_id": 123, "nickname": "N"}) == (31, "vinculada")


def test_si_el_unique_salta_siempre_no_se_queda_dando_vueltas(monkeypatch):
    monkeypatch.setattr(db, "conexion_admin", lambda: _conexion_falsa([None, None, None]))

    @contextmanager
    def usuario(*a, **k):
        raise UniqueViolation()
        yield
    monkeypatch.setattr(db, "conexion_usuario", usuario)
    with pytest.raises(RuntimeError):
        registro.vincular_cuenta_adicional(5, {"meli_user_id": 123})


class _SoloCursor:
    def cursor(self, row_factory=None):
        return SimpleNamespace(execute=lambda *a, **k: None, fetchone=lambda: None)


def test_en_el_login_si_otro_pedido_creo_la_cuenta_se_descarta_el_usuario_nuevo_y_se_sigue_con_la_existente(monkeypatch):
    pool = _Pool([61])                                                                  # el usuario nuevo se crea (id 61)
    monkeypatch.setattr(db, "_obtener_pool", lambda: pool)
    monkeypatch.setattr(db, "liberar_conexion", lambda c: None)
    admin = [None, {"id": 9, "usuario_id": 5}]                                          # 1.ª: no existe · 2.ª (tras el choque): ya existe
    monkeypatch.setattr(db, "conexion_admin", lambda: _conexion_falsa(admin))
    intentos = []

    @contextmanager
    def usuario(*a, **k):
        intentos.append(a)
        if len(intentos) == 1:
            raise UniqueViolation()                                                     # el INSERT de la cuenta choca
        yield _SoloCursor()
    monkeypatch.setattr(db, "conexion_usuario", usuario)
    assert registro.crear_o_actualizar_login({"meli_user_id": 123, "nickname": "N"}) == (5, 9, False)
    assert pool.descartados == [61]                                                     # el usuario que quedó sin cuenta se borra


# ── Racha diaria ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@CON_BASE
def test_con_un_microcorte_la_racha_no_se_da_por_hecha_y_se_reintenta_despues(monkeypatch):
    import app as aplicacion
    import logros
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario_id, cuenta_id = cur.fetchone()
    llamadas = []

    def falla(u, c):
        llamadas.append("falla")
        raise RuntimeError("microcorte de la base")

    monkeypatch.setattr(logros, "actualizar_racha", falla)
    cliente = aplicacion.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario_id, cuenta_id

    cliente.get("/api/alertas/pendientes")
    with cliente.session_transaction() as s:
        assert "racha_actualizada_el" not in s and s["racha_reintento_en"] > 0         # NO se perdió el día: queda pendiente
    cliente.get("/api/alertas/pendientes")
    assert llamadas == ["falla"]                                                        # y no se golpea la base en cada click mientras dura el corte

    with cliente.session_transaction() as s:
        s["racha_reintento_en"] = 0                                                     # pasan los minutos de espera
    monkeypatch.setattr(logros, "actualizar_racha", lambda u, c: llamadas.append("ok") or 3)
    cliente.get("/api/alertas/pendientes")
    with cliente.session_transaction() as s:
        assert s["racha_actualizada_el"] and "racha_reintento_en" not in s
    cliente.get("/api/alertas/pendientes")
    assert llamadas == ["falla", "ok"]                                                  # ya contó: no se vuelve a pedir en el día


def test_la_hora_de_argentina_sale_del_ayudante_compartido_y_no_de_restar_horas_a_mano():
    prohibido = re.compile(r"timedelta\(hours=3\)")
    ofensores = []
    for carpeta in (".", "auth"):
        for nombre in sorted(os.listdir(os.path.join(RAIZ, carpeta))):
            if nombre.endswith(".py"):
                ruta = os.path.join(carpeta, nombre)
                for n, linea in enumerate(_leer(ruta).splitlines(), 1):
                    if prohibido.search(linea) and not linea.lstrip().startswith("#"):
                        ofensores.append(f"{ruta}:{n}")
    assert not ofensores, f"Restan 3 horas a mano en vez de usar utils.hoy_argentina(): {ofensores}"
    assert "hoy_argentina()" in _leer("auth", "middleware.py") and "hoy_local = hoy_argentina()" in _leer("logros.py")


# ── Limpieza de vínculos OAuth abandonados ───────────────────────────────────────────────────────────────────────────────────────────────
def test_la_tarea_borra_los_vinculos_con_mas_de_15_minutos(monkeypatch):
    import scheduler
    consultas = []

    @contextmanager
    def admin():
        class Cursor:
            rowcount = 3

            def execute(self, sql, params=None):
                consultas.append(" ".join(sql.split()))

        yield SimpleNamespace(cursor=lambda: Cursor())

    monkeypatch.setattr(db, "conexion_admin", admin)
    scheduler._tarea_limpiar_vinculaciones_oauth()
    assert consultas == ["DELETE FROM oauth_vinculaciones_pendientes WHERE creado_en < now() - interval '15 minutes'",
                         "DELETE FROM oauth_confirmaciones_pendientes WHERE creado_en < now() - interval '15 minutes'"]


def test_la_limpieza_corre_cada_hora_en_el_scheduler(monkeypatch):
    import scheduler
    trabajos = {}

    class Falso:
        def __init__(self, daemon=True):
            pass

        def add_job(self, funcion, tipo, **kw):
            trabajos[kw["id"]] = (funcion, tipo, kw)

        def start(self):
            pass

    monkeypatch.setattr(scheduler, "BackgroundScheduler", Falso)
    monkeypatch.setattr(scheduler, "_scheduler_apscheduler", None)
    scheduler._arrancar_apscheduler()
    funcion, tipo, kw = trabajos["limpiar_oauth"]
    assert funcion is scheduler._tarea_limpiar_vinculaciones_oauth and tipo == "interval" and kw["hours"] == 1 and kw["max_instances"] == 1
    monkeypatch.setattr(scheduler, "_scheduler_apscheduler", None)


# ── Índices ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@CON_BASE
def test_toda_clave_foranea_tiene_un_indice_que_la_respalde():
    """Sin índice en la columna de la tabla hija, borrar un usuario o una cuenta recorre esa tabla entera. Una migración nueva con una clave foránea tiene que traer su índice."""
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT c.conrelid::regclass::text, a.attname
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
              AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
        """)
        sin_indice = cur.fetchall()
    assert not sin_indice, f"Claves foráneas sin índice: {sin_indice}"


@CON_BASE
def test_el_indice_de_alertas_sin_leer_no_lleva_la_columna_que_el_where_ya_fija():
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_alertas_usuario_no_leidas'")
        definicion = cur.fetchone()[0]
    columnas = definicion.split("(", 1)[1].split(")", 1)[0]
    assert "leida" not in columnas and "usuario_id" in columnas and "creada_en" in columnas and "WHERE (leida = false)" in definicion


def test_las_columnas_codigo_postal_y_localidad_de_ventas_siguen_existiendo_porque_flex_las_usa():
    """Una auditoría las dio por huérfanas: no lo son (todas las ventas las traen y flex.py ubica el envío con ellas). Si se borran, se pierde el destino de cada venta."""
    assert re.search(r"ADD COLUMN IF NOT EXISTS codigo_postal", _leer("migrations", "0019_flex_ubicacion.sql"))
    assert "MAX(localidad)" in _leer("flex.py") and "codigo_postal" in _leer("ventas_sync.py")
    for archivo in sorted(os.listdir(os.path.join(RAIZ, "migrations"))):
        assert not re.search(r"DROP COLUMN[^;]*(codigo_postal|localidad)", _leer("migrations", archivo), re.I), archivo


# ── Workers y capas del CSS ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_la_configuracion_de_gunicorn_trae_dos_workers_por_defecto_y_la_linea_de_comandos_tambien():
    """máquinas × workers × DB_POOL_MAX ≤ 12 de las 15 conexiones de sesión del pooler de Supabase (3 quedan para tareas de administración)."""
    import importlib.util
    monkeypatch_env = os.environ.pop("GUNICORN_WORKERS", None)
    try:
        spec = importlib.util.spec_from_file_location("gunicorn_conf_real", os.path.join(RAIZ, "gunicorn.conf.py"))
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        if monkeypatch_env is not None:
            os.environ["GUNICORN_WORKERS"] = monkeypatch_env
    maquinas = 2                                                                        # `fly status`: 2 máquinas
    pool = int(re.search(r"DB_POOL_MAX = '(\d+)'", _leer("fly.toml")).group(1))
    en_dockerfile = int(re.search(r'"--workers", "(\d+)"', _leer("Dockerfile")).group(1))
    assert modulo.workers == 2 and en_dockerfile == 2
    assert maquinas * max(modulo.workers, en_dockerfile) * pool <= 12
    assert "cpu_count" not in _leer("gunicorn.conf.py")
    # gevent en los dos lados (el worker parchea la biblioteca estándar al arrancar y psycopg 3 coopera con él: medido en Fly): un «sync» dejado en el archivo confunde a quien lo lea
    assert modulo.worker_class == "gevent" and "--worker-class\", \"gevent\"" in _leer("Dockerfile")


def test_el_toast_y_la_busqueda_quedan_por_encima_del_menu_lateral_abierto_pero_la_guia_de_bienvenida_sigue_arriba_de_la_busqueda():
    css = _leer("static", "css", "style.css")
    capas = {nombre: int(z) for nombre, z in re.findall(r"(#toast-container|\.command-overlay\b)[^{]*\{[^}]*?z-index:\s*(\d+)", css, flags=re.S)}
    menu = int(re.search(r"\.sidebar \{[^}]*z-index:\s*(\d+)", _leer("static", "css", "shell.css")).group(1))
    guia = int(re.search(r"#tour-capa \{[^}]*z-index:\s*(\d+)", css).group(1))
    assert capas["#toast-container"] > menu and capas["#toast-container"] > guia
    assert menu < capas[".command-overlay"] < guia


def test_los_archivos_de_la_ruta_vieja_de_vps_ya_no_estan():
    assert not os.path.exists(os.path.join(RAIZ, "deploy"))
    assert "deploy/" not in _leer(".dockerignore").split()
    assert os.path.exists(os.path.join(RAIZ, "gunicorn.conf.py")) and os.path.exists(os.path.join(RAIZ, "Dockerfile"))

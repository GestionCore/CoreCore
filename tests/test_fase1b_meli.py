"""
Fase 1, puntos 7 y 8 de la auditoría. Formas reales capturadas con la API el 2026-10-07:
· POST /items/validate sin datos obligatorios → 400 {"error": "validation_error", "cause": [{"code": "body.required_fields", "message": "... properties [family_name]"}]}
· GET /questions/search → cada pregunta trae `date_created` (con hasta 9 decimales y -04:00) y NINGÚN campo de plazo.
· GET /flex/sites/MLA/users/{id}/services → 404 (no existe): el punto 6 queda en espera.
"""
import os
from datetime import datetime, timedelta, timezone

import meli_errores
import preguntas_sla
import stock_meli

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = {"cause": [{"department": "items", "cause_id": 369, "type": "error", "code": "body.required_fields", "references": ["body"],
                   "message": "The body does not contains some or none of the following properties [family_name]"}],
        "message": "body.required_fields", "error": "validation_error", "status": 400}


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


class Resp:
    def __init__(self, estado, cuerpo):
        self.status_code, self._cuerpo, self.text = estado, cuerpo, str(cuerpo)

    def json(self):
        return self._cuerpo


# ── 7. Atributos obligatorios faltantes ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_rechazo_real_por_datos_obligatorios_se_explica_con_los_nombres_en_castellano():
    assert meli_errores.atributos_faltantes(REAL) == ["Nombre de familia"]
    frase = meli_errores.explicar_error_meli(400, REAL)
    assert "faltan datos obligatorios" in frase and "Nombre de familia" in frase and "Editalos desde Mercado Libre primero" in frase
    assert "family_name" not in frase and "body" not in frase                                  # nada de códigos ni inglés


def test_los_codigos_documentados_de_atributos_obligatorios_tambien_se_reconocen():
    doc = {"error": "validation_error", "cause": [{"code": "item.attributes.missing_required", "references": ["item.attributes"], "message": "Attributes [BRAND, GTIN, MODEL] are required"}]}
    assert meli_errores.atributos_faltantes(doc) == ["Marca", "Código universal (GTIN/EAN)", "Modelo"]
    por_referencia = {"cause": [{"code": "item.attributes.invalid", "references": ["item.attributes.COLOR"], "message": "attribute COLOR is required"}]}
    assert meli_errores.atributos_faltantes(por_referencia) == ["Color"]
    sin_nombres = {"cause": [{"code": "item.attributes.missing", "references": ["item.attributes"], "message": "missing"}]}
    assert meli_errores.atributos_faltantes(sin_nombres) == [] and "marca, modelo, código" in meli_errores.explicar_error_meli(400, sin_nombres)


def test_un_validation_error_suelto_no_se_hace_pasar_por_atributos_faltantes():
    """Hay muchos otros rechazos de validación (precio, título…): decir «faltan atributos» sería mentir."""
    precio = {"error": "validation_error", "message": "Validation error", "status": 400, "cause": [{"code": "item.price.invalid", "message": "invalid price"}]}
    assert meli_errores.atributos_faltantes(precio) is None
    assert meli_errores.explicar_error_meli(400, precio) == "Mercado Libre no aceptó ese precio."
    assert meli_errores.atributos_faltantes({"error": "validation_error"}) is None and meli_errores.atributos_faltantes(None) is None
    assert meli_errores.atributos_faltantes({"cause": ["basura", None]}) is None


def test_solo_un_400_se_explica_como_datos_faltantes():
    assert "datos obligatorios" not in meli_errores.explicar_error_meli(500, REAL)
    assert "datos obligatorios" not in meli_errores.explicar_error_meli(404, REAL)


def test_el_ajuste_de_stock_por_una_venta_cuenta_el_motivo_real_en_vez_de_un_generico():
    item = {"available_quantity": 5}
    ok, mensaje, nuevo = stock_meli.ajustar_en_meli("tok", "MLA1", "MLA1_unica", -1, obtener=lambda *a, **k: Resp(200, item), escribir=lambda *a, **k: Resp(400, REAL))
    assert ok is False and nuevo is None and "faltan datos obligatorios" in mensaje


def test_el_stock_masivo_cuenta_aparte_las_publicaciones_que_piden_datos_y_las_nombra():
    app = _leer("app.py")
    cuerpo = app[app.index("def actualizar_stock_multiple"):app.index("def despacho_marcar")]
    assert "meli_errores.atributos_faltantes(meli_errores.cuerpo_de(r))" in cuerpo and "sin_atributos" in cuerpo and "editalos desde Mercado Libre primero" in cuerpo
    assert "if r.status_code == 400 else None" in cuerpo                                           # solo un 400 puede ser esto


# ── 8. Preguntas: hora real y objetivo de respuesta ────────────────────────────────────────────────────────────────────────────────────────
def test_la_fecha_de_la_pregunta_se_lee_aunque_mercado_libre_mande_nueve_decimales():
    f = preguntas_sla.fecha_de_meli("2026-04-18T09:03:35.262291905-04:00")
    assert f == datetime(2026, 4, 18, 13, 3, 35, 262291, tzinfo=timezone.utc)                       # el instante correcto (-04:00 = 13:03 UTC)
    assert preguntas_sla.fecha_de_meli("2026-04-18T09:03:35-03:00").utcoffset() == timedelta(hours=-3)
    assert preguntas_sla.fecha_de_meli(None) is None and preguntas_sla.fecha_de_meli("") is None and preguntas_sla.fecha_de_meli("ayer") is None


def test_el_limite_es_una_hora_desde_que_entro_y_sin_fecha_no_hay_limite():
    f = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    assert preguntas_sla.limite_de(f) == f + timedelta(minutes=60) and preguntas_sla.SLA_MINUTOS == 60
    assert preguntas_sla.limite_de(None) is None


def test_la_urgencia_distingue_vencida_por_vencer_y_a_tiempo():
    limite = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)
    antes = lambda m: limite - timedelta(minutes=m)                                                 # noqa: E731
    assert preguntas_sla.urgencia(limite, antes(40)) == ("a_tiempo", 40)
    assert preguntas_sla.urgencia(limite, antes(15)) == ("por_vencer", 15)
    assert preguntas_sla.urgencia(limite, antes(1))[0] == "por_vencer"
    estado, faltan = preguntas_sla.urgencia(limite, limite + timedelta(minutes=25))
    assert estado == "vencida" and faltan == -25
    assert preguntas_sla.urgencia(None) == ("sin_dato", None)


def test_el_sync_guarda_la_hora_de_mercado_libre_y_el_limite_y_la_lista_ordena_por_urgencia():
    sync = _leer("devoluciones_sync.py")
    assert 'preguntas_sla.fecha_de_meli(p.get("date_created"))' in sync and "fecha_pregunta, hora_limite_respuesta" in sync
    assert "fecha_pregunta = excluded.fecha_pregunta, hora_limite_respuesta = excluded.hora_limite_respuesta" in sync
    app = _leer("app.py")
    lista = app[app.index("def api_preguntas_lista"):app.index("def api_preguntas_responder")]
    assert "ORDER BY p.hora_limite_respuesta ASC NULLS LAST, p.creado_en ASC" in lista and '"limite_iso"' in lista and "astimezone(ARGENTINA)" in lista


def test_la_migracion_agrega_las_dos_columnas_sin_inventar_datos_y_aclara_que_el_limite_es_interno():
    sql = _leer("migrations", "0040_preguntas_sla.sql")
    assert "fecha_pregunta TIMESTAMPTZ" in sql and "hora_limite_respuesta TIMESTAMPTZ" in sql and "NO trae ningún campo de plazo" in sql
    assert "UPDATE" not in sql.upper() and "DROP" not in sql.upper()


def test_la_pantalla_muestra_el_objetivo_y_no_se_lo_atribuye_a_mercado_libre():
    t = _leer("templates", "_dia_preguntas.html")
    assert "function plazo(p)" in t and "Pasó el objetivo hace" in t and "Mercado Libre no informa un plazo por pregunta" in t
    assert "penaliza" not in t.lower()
    assert "la más urgente" in t


def test_en_la_base_real_las_columnas_nuevas_existen():
    import pytest
    if not os.getenv("DATABASE_URL"):
        pytest.skip("Sin DATABASE_URL")
    import db
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'preguntas_pendientes'")
        columnas = {f[0] for f in cur.fetchall()}
    assert {"fecha_pregunta", "hora_limite_respuesta"} <= columnas


# ── «Descargar mis datos»: cada carpeta solo con las filas de su cuenta ───────────────────────────────────────────────────────────────────
def test_descargar_mis_datos_filtra_cada_carpeta_por_su_cuenta_aunque_la_tabla_sea_de_la_persona():
    """auditoria, avisos y comentarios filtran por usuario (no por cuenta): sin este filtro cada carpeta traía también lo de las otras cuentas (se vio cuando entró el primer registro de otra cuenta)."""
    import mis_datos

    class Cursor:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(sql)

        def copy(self, sql):
            self.sql.append(sql)
            raise RuntimeError("corta acá: solo importa el SQL")

    c = Cursor()
    mis_datos._csv_de_tabla(c, "auditoria", cuenta_id=7)
    assert any('COPY (SELECT * FROM "auditoria" WHERE cuenta_id = 7)' in q for q in c.sql)
    c2 = Cursor()
    mis_datos._csv_de_tabla(c2, "auditoria", sin_cuenta=True)
    assert any('WHERE cuenta_id IS NULL' in q for q in c2.sql)
    assert "int(cuenta_id)" in _leer("mis_datos.py")                                                  # el id entra como entero, nunca como texto suelto

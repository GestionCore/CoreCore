"""Sync de reclamos: no vuelve a pedir en cada ciclo lo que cambia poco, y escribe siempre en el mismo orden (evita el deadlock entre dos sincronizaciones)."""
import contextlib

import cache_db
import db
import devoluciones_sync as d

AHORA = 5_000_000.0


def test_filtrar_por_vigencia_pide_lo_nuevo_y_lo_vencido():
    consultados = {"A": AHORA - 60, "B": AHORA - 7300}
    assert d.filtrar_por_vigencia(["A", "B", "C"], consultados, AHORA, 7200) == ["B", "C"]      # A es reciente; B venció; C nunca se consultó
    assert d.filtrar_por_vigencia(["A"], {}, AHORA, 7200) == ["A"]
    assert d.filtrar_por_vigencia(["A"], None, AHORA, 7200) == ["A"]
    assert d.filtrar_por_vigencia([], consultados, AHORA, 7200) == []


def test_la_memoria_de_lo_consultado_descarta_lo_de_hace_mas_de_un_dia():
    memoria = d._sin_vencidos({"viejo": AHORA - 90_000, "nuevo": AHORA - 10}, AHORA)
    assert memoria == {"nuevo": AHORA - 10}


class _Cursor:
    def __init__(self):
        self.upserts = []

    def execute(self, sql, params=None):
        if "INSERT INTO incidencias_posventa" in sql:
            self.upserts.append(params[1])               # id_reclamo

    def fetchone(self):
        return None

    rowcount = 0


class _Respuesta:
    status_code = 200

    def __init__(self, claims):
        self._claims = claims

    def json(self):
        return {"data": self._claims}


def test_los_reclamos_se_escriben_ordenados_por_id(monkeypatch):
    cursor = _Cursor()

    @contextlib.contextmanager
    def conexion(*a, **k):
        yield type("Con", (), {"cursor": lambda self: cursor})()

    claims = [{"id": 3000, "status": "opened", "type": "mediations"}, {"id": 1000, "status": "opened", "type": "mediations"}, {"id": 2000, "status": "opened", "type": "mediations"}]
    monkeypatch.setattr(db, "conexion_usuario", conexion)
    monkeypatch.setattr(d.meli_http, "get", lambda *a, **k: _Respuesta(claims))
    monkeypatch.setattr(d, "_motivo_oficial", lambda headers, reason_id: None)
    for nombre in ("_actualizar_impacto_en_reputacion", "_actualizar_dinero_retenido", "_completar_motivos_viejos"):
        monkeypatch.setattr(d, nombre, lambda *a, **k: None)
    d.sincronizar_reclamos(1, 1, "token", "999")
    assert cursor.upserts == ["1000", "2000", "3000"]


def test_un_reclamo_ya_consultado_no_vuelve_a_pedir_su_impacto(monkeypatch):
    """Dos reclamos abiertos: uno se consultó hace 10 minutos y el otro nunca. Solo se pide el segundo."""
    pedidos = []

    class _C:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return []

    @contextlib.contextmanager
    def conexion(*a, **k):
        yield type("Con", (), {"cursor": lambda self: _C()})()

    monkeypatch.setattr(db, "conexion_usuario", conexion)
    monkeypatch.setattr(d.time, "time", lambda: AHORA)
    monkeypatch.setattr(cache_db, "leer", lambda cursor, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None: (True, {"111": AHORA - 600}))
    monkeypatch.setattr(cache_db, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(d, "_impacto_en_reputacion", lambda headers, id_reclamo: (pedidos.append(id_reclamo), "affected")[1])
    d._actualizar_impacto_en_reputacion(1, 1, {}, ["111", "222"])
    assert pedidos == ["222"]

"""
Sincronización de órdenes: una página que Mercado Libre rechaza NO se toma como «no hay más». Antes devolvía una lista vacía, el sync daba el rango por terminado, avanzaba
`ultima_sincronizacion_ventas` y las órdenes que no se trajeron se perdían cuando pasaba el colchón de 2 horas. Mercado Libre y la base se simulan.
"""
from datetime import datetime, timedelta, timezone

import pytest

import ventas_sync

UTC = timezone.utc
AHORA = datetime(2030, 3, 20, 15, 0, tzinfo=UTC)


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo, self.text = codigo, cuerpo or {}, str(cuerpo)

    def json(self):
        return self._cuerpo


def _orden(n):
    return {"id": n}


def test_una_pagina_rechazada_levanta_un_error_en_vez_de_devolver_vacio(monkeypatch):
    monkeypatch.setattr(ventas_sync.meli_http, "get", lambda *a, **k: _Resp(403, {"message": "forbidden"}))
    with pytest.raises(ventas_sync.PaginaDeOrdenesRechazada) as error:
        ventas_sync._obtener_pagina_ordenes("token", 123, AHORA - timedelta(days=1), AHORA, 50)
    assert "403" in str(error.value) and "offset 50" in str(error.value)


def test_una_pagina_buena_devuelve_las_ordenes_y_el_total(monkeypatch):
    monkeypatch.setattr(ventas_sync.meli_http, "get", lambda *a, **k: _Resp(200, {"results": [_orden(1), _orden(2)], "paging": {"total": 2}}))
    assert ventas_sync._obtener_pagina_ordenes("token", 123, AHORA - timedelta(days=1), AHORA, 0) == ([_orden(1), _orden(2)], 2)


def test_un_rango_sin_ordenes_es_un_final_normal_y_no_un_error(monkeypatch):
    monkeypatch.setattr(ventas_sync.meli_http, "get", lambda *a, **k: _Resp(200, {"results": [], "paging": {"total": 0}}))
    assert ventas_sync._sincronizar_rango(1, 1, "token", 123, AHORA - timedelta(days=1), AHORA) == (0, 0)


def test_si_la_segunda_pagina_se_rechaza_el_rango_no_se_da_por_terminado(monkeypatch):
    paginas = [_Resp(200, {"results": [_orden(1)], "paging": {"total": 120}}),            # el pedido de prueba del total
               _Resp(200, {"results": [_orden(n) for n in range(50)], "paging": {"total": 120}}),
               _Resp(500, {"message": "error interno"})]                                       # la segunda página (offset 50) falla
    monkeypatch.setattr(ventas_sync.meli_http, "get", lambda *a, **k: paginas.pop(0))
    escritas = []
    monkeypatch.setattr(ventas_sync, "_escribir_pagina", lambda cursor, cuenta, ordenes, token: escritas.append(len(ordenes)) or (len(ordenes), len(ordenes)))
    monkeypatch.setattr(ventas_sync.time, "sleep", lambda s: None)

    class _Prestada:
        def __enter__(self):
            class _C:
                def cursor(self):
                    return object()
            return _C()

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(ventas_sync.db, "conexion_usuario", lambda u, c=None: _Prestada())
    with pytest.raises(ventas_sync.PaginaDeOrdenesRechazada):
        ventas_sync._sincronizar_rango(1, 1, "token", 123, AHORA - timedelta(days=1), AHORA)
    assert escritas == [50]                                                                 # lo de la primera página sí quedó guardado (reprocesarlo después es seguro)


def test_si_un_pedido_falla_la_marca_de_la_ultima_sincronizacion_no_avanza(monkeypatch):
    ejecutadas = []

    class _Cursor:
        def execute(self, sql, params=None):
            ejecutadas.append(" ".join(sql.split()))

        def fetchone(self):
            return (AHORA - timedelta(hours=3),)

    class _Prestada:
        def __enter__(self):
            class _C:
                def cursor(self):
                    return _Cursor()
            return _C()

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(ventas_sync.db, "conexion_usuario", lambda u, c=None: _Prestada())

    def _falla(*a, **k):
        raise ventas_sync.PaginaDeOrdenesRechazada("Mercado Libre respondió 403")
    monkeypatch.setattr(ventas_sync, "_sincronizar_rango", _falla)
    with pytest.raises(ventas_sync.PaginaDeOrdenesRechazada):
        ventas_sync.sincronizar_ventas(1, 1, "token", 123)
    assert not [sql for sql in ejecutadas if "UPDATE cuentas_meli SET ultima_sincronizacion_ventas" in sql]          # la marca se queda donde estaba: la próxima pasada reintenta desde ahí
    assert any("SELECT ultima_sincronizacion_ventas" in sql for sql in ejecutadas)


def test_sincronizar_todo_atrapa_el_error_y_lo_reporta_sin_frenar_el_resto(monkeypatch):
    import sincronizador
    reportes = []

    def _falla(*a, **k):
        raise ventas_sync.PaginaDeOrdenesRechazada("Mercado Libre respondió 403")
    monkeypatch.setattr(sincronizador.ventas_sync, "sincronizar_ventas", _falla)
    monkeypatch.setattr(sincronizador.monitoreo, "reportar", lambda fase, error, cuenta_id=None: reportes.append((fase, type(error).__name__, cuenta_id)))
    # Se prueba solo la parte que envuelve a ventas: el resto de la sincronización completa se reemplaza por funciones vacías
    for nombre in ("sincronizar_catalogo",):
        monkeypatch.setattr(sincronizador, nombre, lambda *a, **k: None)
    monkeypatch.setattr(sincronizador.token_manager, "asegurar_token_valido", lambda cuenta: "token")
    monkeypatch.setattr(sincronizador.devoluciones_sync, "sincronizar_posventa", lambda *a, **k: None)
    monkeypatch.setattr(sincronizador.capacidades, "refrescar_si_hace_falta", lambda *a, **k: {})
    monkeypatch.setattr(sincronizador.enriquecimiento, "refrescar_todo", lambda *a, **k: None)

    class _Cursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (555,)

    class _Prestada:
        def __enter__(self):
            class _C:
                def cursor(self):
                    return _Cursor()
            return _C()

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(sincronizador.db, "conexion_usuario", lambda u, c=None: _Prestada())
    sincronizador._sincronizar_todo_interno(1, 9)                                    # no levanta
    assert ("ventas", "PaginaDeOrdenesRechazada", 9) in reportes

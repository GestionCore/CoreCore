"""
Evolución mensual de Ganancia Real (metricas.obtener_evolucion_mensual): la publicidad de cada mes se guarda en la caché compartida (antes se pedía a Mercado Libre en cada visita y tardaba ~20 s
con la máquina fría) y un mes sin dato de publicidad se marca en vez de contarse como «$0». Números hechos a mano; Mercado Libre y la base se simulan.
"""
from datetime import date, timedelta

import metricas

HOY = date(2026, 10, 21)
GASTO = {"2026-08": 1000.0, "2026-09": 2000.0, "2026-10": 500.0}            # lo que Mercado Libre informa (los meses más viejos quedan fuera de sus 90 días)


class _Cursor:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self.filas


class _Conexion:
    def __init__(self, filas):
        self.filas = filas

    def cursor(self, **k):
        return _Cursor(self.filas)


class _Prestada:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return _Conexion(self.filas)

    def __exit__(self, *a):
        return False


def _preparar(monkeypatch, ventas_por_mes=None, falla=()):
    """La caché compartida es un diccionario {clave: (firma, valor)}; devuelve (caché, llamadas a Mercado Libre)."""
    cache, llamadas = {}, []
    filas = [{"mes": mes, "facturado": f, "comision": c, "envios": e, "costo_fabricacion": k} for mes, (f, c, e, k) in (ventas_por_mes or {}).items()]
    monkeypatch.setattr(metricas, "hoy_argentina", lambda: HOY)
    monkeypatch.setattr(metricas.db, "conexion_usuario", lambda u, c=None: _Prestada(filas))
    monkeypatch.setattr(metricas.ads, "obtener_advertiser_id", lambda token, cuenta: "ADV")

    def _gasto(token, advertiser, desde, hasta):
        llamadas.append((desde, hasta))
        if date.fromisoformat(desde) < HOY - timedelta(days=ads_historia()) or desde[:7] in falla:
            return None
        return GASTO.get(desde[:7], 0.0)
    monkeypatch.setattr(metricas.ads, "obtener_gasto_ads_total_periodo", _gasto)

    def _leer(cursor, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None):
        guardado = cache.get(clave)
        return (True, guardado[1]) if guardado and guardado[0] == firma else (False, None)
    monkeypatch.setattr(metricas.cache_db, "leer", _leer)
    monkeypatch.setattr(metricas.cache_db, "guardar", lambda cursor, cuenta, clave, valor, firma="": cache.__setitem__(clave, (firma, valor)))
    return cache, llamadas


def ads_historia():
    return metricas.ads.DIAS_HISTORIA_ADS


def test_los_meses_con_publicidad_la_suman_y_los_que_mercado_libre_ya_no_informa_se_marcan(monkeypatch):
    # Facturado, comisión, envíos y fabricación de agosto: 10.000 − (1.500 + 500 + 3.000 + 1.000 de publicidad) = 4.000 de resultado
    _preparar(monkeypatch, {"2026-08": (10000.0, 1500.0, 500.0, 3000.0), "2026-06": (8000.0, 1000.0, 400.0, 2000.0)})
    serie = {m["mes"]: m for m in metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)}
    assert list(serie) == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert serie["2026-08"]["costos"] == 6000.0 and serie["2026-08"]["resultado_neto"] == 4000.0 and serie["2026-08"]["sin_publicidad"] is False
    assert serie["2026-06"]["costos"] == 3400.0 and serie["2026-06"]["resultado_neto"] == 4600.0       # sin publicidad: no se inventa un costo
    assert [serie[m]["sin_publicidad"] for m in ("2026-05", "2026-06", "2026-07")] == [True, True, True]
    assert serie["2026-09"]["costos"] == 2000.0 and serie["2026-10"]["costos"] == 500.0 and serie["2026-10"]["sin_publicidad"] is False


def test_la_segunda_visita_no_vuelve_a_pedir_la_publicidad_de_los_meses_ya_guardados(monkeypatch):
    cache, llamadas = _preparar(monkeypatch)
    metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)
    primera = len(llamadas)
    assert primera == 6                                                                                  # 6 meses, una llamada cada uno
    assert sorted(cache) == ["ads_gasto_mes:2026-08", "ads_gasto_mes:2026-09", "ads_gasto_mes:2026-10"]  # solo lo que Mercado Libre contestó: lo demás no se guarda como $0
    assert cache["ads_gasto_mes:2026-09"] == ("cerrado", 2000.0) and cache["ads_gasto_mes:2026-10"] == ("abierto", 500.0)
    metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)
    assert len(llamadas) == primera + 3                                                                  # solo los 3 meses sin dato se vuelven a intentar (por si Mercado Libre ya los informa)


def test_un_error_de_mercado_libre_en_un_mes_con_dato_no_se_guarda_como_cero(monkeypatch):
    cache, _ = _preparar(monkeypatch, falla=("2026-09",))
    serie = {m["mes"]: m for m in metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)}
    assert "ads_gasto_mes:2026-09" not in cache and serie["2026-09"]["sin_publicidad"] is True
    assert serie["2026-08"]["costos"] == 1000.0 and "ads_gasto_mes:2026-08" in cache


def test_lo_guardado_a_mitad_de_mes_no_vale_como_mes_cerrado(monkeypatch):
    cache, llamadas = _preparar(monkeypatch)
    cache["ads_gasto_mes:2026-09"] = ("abierto", 123.0)                                                  # septiembre se guardó mientras estaba en curso: tiene que volver a pedirse
    serie = {m["mes"]: m for m in metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)}
    assert serie["2026-09"]["costos"] == 2000.0 and cache["ads_gasto_mes:2026-09"] == ("cerrado", 2000.0)
    assert ("2026-09-01", "2026-09-30") in llamadas


def test_un_mes_cerrado_guardado_sigue_disponible_aunque_ya_este_fuera_de_los_90_dias_de_mercado_libre(monkeypatch):
    cache, llamadas = _preparar(monkeypatch)
    cache["ads_gasto_mes:2026-07"] = ("cerrado", 777.0)                                                  # se guardó cuando todavía se podía pedir
    serie = {m["mes"]: m for m in metricas.obtener_evolucion_mensual(1, 1, "token", meses=6)}
    assert serie["2026-07"]["costos"] == 777.0 and serie["2026-07"]["sin_publicidad"] is False
    assert ("2026-07-01", "2026-07-31") not in llamadas


def test_sin_cuenta_de_publicidad_ningun_mes_inventa_un_costo(monkeypatch):
    _preparar(monkeypatch)
    monkeypatch.setattr(metricas.ads, "obtener_advertiser_id", lambda token, cuenta: None)
    serie = metricas.obtener_evolucion_mensual(1, 1, "token", meses=3)
    assert all(m["sin_publicidad"] and m["costos"] == 0.0 for m in serie)


# ── La factura de Mercado Libre en la misma pantalla ───────────────────────────────────────────────────────────────────────────────────────

def test_la_factura_condensada_se_guarda_y_la_segunda_visita_no_llama_a_mercado_libre(monkeypatch):
    import facturacion
    cache, llamadas = {}, []
    monkeypatch.setattr(facturacion, "resumen_condensado_periodo_actual", lambda token, cuenta, group="ML": llamadas.append(1) or {"filas": [{"label": "Cargos por venta", "monto": 500.0}], "en_curso": True})
    import db
    monkeypatch.setattr(db, "conexion_usuario", lambda u, c=None: _Prestada([]))
    import cache_db
    monkeypatch.setattr(cache_db, "leer", lambda cursor, cuenta, clave, firma="", ttl_segundos=3600, ttl_fallido=None: (True, cache[clave]) if clave in cache else (False, None))
    monkeypatch.setattr(cache_db, "guardar", lambda cursor, cuenta, clave, valor, firma="": cache.__setitem__(clave, valor))
    primero = facturacion.resumen_condensado_con_cache(1, 1, "token")
    segundo = facturacion.resumen_condensado_con_cache(1, 1, "token")
    assert primero == segundo and primero["filas"][0]["monto"] == 500.0 and len(llamadas) == 1


def test_si_mercado_libre_no_contesta_la_factura_no_se_guarda_vacia(monkeypatch):
    import cache_db
    import db
    import facturacion
    cache = {}
    monkeypatch.setattr(facturacion, "resumen_condensado_periodo_actual", lambda token, cuenta, group="ML": None)
    monkeypatch.setattr(db, "conexion_usuario", lambda u, c=None: _Prestada([]))
    monkeypatch.setattr(cache_db, "leer", lambda *a, **k: (False, None))
    monkeypatch.setattr(cache_db, "guardar", lambda cursor, cuenta, clave, valor, firma="": cache.__setitem__(clave, valor))
    assert facturacion.resumen_condensado_con_cache(1, 1, "token") is None and cache == {}


def test_la_pantalla_marca_con_asterisco_el_mes_sin_publicidad():
    from jinja2 import Environment
    plantilla = Environment().from_string("{% if serie | selectattr('sin_publicidad') | list %}AVISO{% endif %}")
    assert plantilla.render(serie=[{"sin_publicidad": False}, {"sin_publicidad": True}]) == "AVISO"
    assert plantilla.render(serie=[{"sin_publicidad": False}]) == ""

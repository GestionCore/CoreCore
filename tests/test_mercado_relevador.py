"""
Relevador global de mercado (mercado_relevador.py, mercado_categorias.py): el trabajo diario que arma la historia de las tablas globales de la migración 0045.

  · cálculos con números hechos a mano (estado de las palabras en alza, estadísticas de ofertas) y la lectura de las respuestas de Mercado Libre, sin red;
  · una corrida COMPLETA contra el esquema real de la base, con Mercado Libre simulado, dentro de una transacción que siempre se revierte.
"""
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

import mercado_categorias
import mercado_relevador as rel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


class _SinEspera:
    """Reemplazo de `time` para no esperar entre pedidos en las pruebas."""
    @staticmethod
    def sleep(_):
        return None

    time = staticmethod(__import__("time").time)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(rel, "time", _SinEspera)


# ── Palabras en alza ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_las_palabras_se_normalizan_a_minusculas_y_espacios_simples():
    assert rel.normalizar_palabra("  iPhone   15  PRO ") == "iphone 15 pro"
    assert rel.normalizar_palabra(None) == "" and rel.normalizar_palabra("   ") == ""


def test_las_palabras_en_alza_conservan_el_orden_y_no_repiten_ni_traen_vacias(monkeypatch):
    lista = [{"keyword": "iPhone 15"}, {"keyword": "celular samsung"}, {"keyword": "IPHONE  15"}, {"keyword": " "}, {"keyword": None}, {"keyword": "xiaomi"}]
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (200, lista))
    assert rel.palabras_en_alza(rel.Cliente("t"), "MLA1055") == ["iphone 15", "celular samsung", "xiaomi"]


def test_las_palabras_en_alza_se_cortan_en_cien_y_la_lista_general_usa_la_ruta_del_sitio(monkeypatch):
    pedidos = []

    def falso(ruta, headers, params=None, timeout=12):
        pedidos.append(ruta)
        return 200, [{"keyword": f"palabra {i}"} for i in range(150)]
    monkeypatch.setattr(mercado_categorias, "_get", falso)
    assert len(rel.palabras_en_alza(rel.Cliente("t"), "MLA")) == 100
    rel.palabras_en_alza(rel.Cliente("t"), "MLA1055")
    assert pedidos == ["/trends/MLA", "/trends/MLA/MLA1055"]


def test_una_categoria_sin_lista_de_tendencias_no_cuenta_como_error_pero_un_fallo_si(monkeypatch):
    cliente = rel.Cliente("t")
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (404, None))
    assert rel.palabras_en_alza(cliente, "MLA1") is None and cliente.errores == []
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (500, None))
    assert rel.palabras_en_alza(cliente, "MLA1") is None and len(cliente.errores) == 1


def test_el_estado_de_una_palabra_suma_dias_seguidos_y_se_corta_si_falta_un_dia():
    d = date(2030, 1, 10)
    previo = {
        1: {"primera_vez": date(2030, 1, 1), "ultima_vez": date(2030, 1, 9), "racha_dias": 3, "dias_en_lista": 5, "mejor_posicion": 4, "posicion_actual": 4},
        2: {"primera_vez": date(2030, 1, 2), "ultima_vez": date(2030, 1, 5), "racha_dias": 2, "dias_en_lista": 2, "mejor_posicion": 1, "posicion_actual": 1},
        3: {"primera_vez": date(2030, 1, 1), "ultima_vez": date(2030, 1, 6), "racha_dias": 1, "dias_en_lista": 1, "mejor_posicion": 9, "posicion_actual": None},
        4: {"primera_vez": date(2030, 1, 3), "ultima_vez": date(2030, 1, 9), "racha_dias": 7, "dias_en_lista": 7, "mejor_posicion": 5, "posicion_actual": 5},
    }
    filas = {f[0]: f for f in rel.calcular_estado(previo, [2, 1, 9], d, {1: 7})}
    assert filas[1] == (1, date(2030, 1, 1), d, 4, 6, 2, 2, 7)                  # seguida: racha 4, 6 días en total, mejor puesto 2 (antes 4), hace una semana era el 7
    assert filas[2] == (2, date(2030, 1, 2), d, 1, 3, 1, 1, None)               # faltó del 6 al 9: la racha vuelve a 1 pero suma el día a los totales
    assert filas[9] == (9, d, d, 1, 1, 3, 3, None)                              # nueva
    assert filas[4] == (4, date(2030, 1, 3), date(2030, 1, 9), 7, 7, 5, None, None)   # salió: conserva su historia y ya no tiene puesto
    assert 3 not in filas                                                        # ya había salido antes: nada que actualizar


def test_repetir_la_corrida_del_mismo_dia_no_suma_dias_ni_rachas():
    d = date(2030, 1, 10)
    previo = {1: {"primera_vez": date(2030, 1, 8), "ultima_vez": d, "racha_dias": 3, "dias_en_lista": 3, "mejor_posicion": 2, "posicion_actual": 2}}
    assert rel.calcular_estado(previo, [5, 1], d, {}) == [(5, d, d, 1, 1, 1, 1, None), (1, date(2030, 1, 8), d, 3, 3, 2, 2, None)]


# ── Estadísticas de las ofertas de una muestra ───────────────────────────────────────────────────────────────────────────────────────────
def _oferta(precio, vendedor, full=False, gratis=False, oficial=False, original=None, categoria="MLA1"):
    return {"price": precio, "seller_id": vendedor, "category_id": categoria, "original_price": original, "official_store_id": 99 if oficial else None,
            "shipping": {"logistic_type": "fulfillment" if full else "xd_drop_off", "free_shipping": gratis}}


def _ofertas_de_ejemplo():
    precios = [1000] * 8 + [2000] * 4 + [3000] * 2 + [4000, 5000]
    vendedores = ["A"] * 8 + ["B"] * 4 + ["C"] * 2 + ["D", "E"]
    ofertas = [_oferta(p, v) for p, v in zip(precios, vendedores)]
    for i in range(4):
        ofertas[i]["shipping"]["logistic_type"] = "fulfillment"
    for i in range(8):
        ofertas[i]["shipping"]["free_shipping"] = True
    ofertas[0]["official_store_id"] = ofertas[1]["official_store_id"] = 99
    for i, original in ((0, 1250), (8, 2500), (9, 2500), (12, 3750)):          # cuatro ofertas con 20 % de descuento
        ofertas[i]["original_price"] = original
    return ofertas


def test_las_estadisticas_de_una_muestra_con_numeros_hechos_a_mano():
    e = rel.estadisticas_de_ofertas(_ofertas_de_ejemplo(), productos=6)
    assert (e["muestra_productos"], e["muestra_ofertas"], e["muestra_vendedores"]) == (6, 16, 5)
    assert (e["precio_min"], e["precio_p25"], e["precio_p50"], e["precio_p75"], e["precio_max"]) == (1000.0, 1000.0, 1500.0, 2250.0, 5000.0)
    assert (e["pct_full"], e["pct_envio_gratis"], e["pct_tienda_oficial"], e["pct_con_descuento"], e["descuento_promedio"]) == (25.0, 50.0, 12.5, 25.0, 20.0)
    assert e["concentracion_top3"] == 87.5 and e["hhi"] == 3359                  # (8+4+2)/16 · 50² + 25² + 12,5² + 2 × 6,25²


def test_con_pocas_ofertas_no_se_calcula_la_concentracion_de_vendedores():
    e = rel.estadisticas_de_ofertas(_ofertas_de_ejemplo()[:14], productos=2)
    assert e["muestra_ofertas"] == 14 and e["concentracion_top3"] is None and e["hhi"] is None and e["precio_p50"] is not None


def test_sin_ofertas_los_precios_quedan_vacios_y_no_en_cero():
    e = rel.estadisticas_de_ofertas([], productos=3)
    assert e["muestra_ofertas"] == 0 and e["muestra_productos"] == 3
    assert e["precio_min"] is None and e["precio_p50"] is None and e["pct_full"] is None and e["descuento_promedio"] is None


# ── Lectura de Mercado Libre ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_los_atributos_de_variacion_y_los_ocultos_salen_de_las_marcas_de_mercado_libre():
    atributos = [
        {"id": "COLOR", "tags": {"allow_variations": True, "defines_picture": True, "required": True}},
        {"id": "INTERNAL_MEMORY", "tags": {}},                                               # visible y sin marca de variación: lo decide la familia (variantes.py)
        {"id": "GTIN", "tags": {"hidden": True, "variation_attribute": True}},
        {"id": "PACKAGE_WEIGHT", "tags": {"hidden": True, "read_only": True, "variation_attribute": True}},
        {"id": "MAIN_COLOR", "tags": {"variation_attribute": True}},
        {"tags": {"hidden": True}},                                                          # sin id: se ignora
    ]
    assert mercado_categorias.clasificar_atributos(atributos) == (["COLOR"], ["GTIN", "PACKAGE_WEIGHT"])
    assert mercado_categorias.clasificar_atributos(None) == ([], [])


def test_se_lee_una_categoria_con_su_camino_su_dominio_y_su_tamano(monkeypatch):
    respuesta = {"id": "MLA5232", "name": "De Mano", "total_items_in_this_category": 32821, "children_categories": [],
                 "path_from_root": [{"id": "MLA1", "name": "Herramientas"}, {"id": "MLA9", "name": "Taladros"}, {"id": "MLA5232", "name": "De Mano"}],
                 "settings": {"catalog_domain": "MLA-ELECTRIC_DRILLS", "max_title_length": 60, "max_variations_allowed": 100}}
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (200, respuesta))
    c = mercado_categorias.leer_categoria({}, "MLA5232")
    assert c == {"category_id": "MLA5232", "nombre": "De Mano", "parent_id": "MLA9", "camino": ["MLA1", "MLA9", "MLA5232"], "camino_nombres": ["Herramientas", "Taladros", "De Mano"],
                 "dominio_id": "MLA-ELECTRIC_DRILLS", "es_hoja": True, "max_titulo": 60, "max_variaciones": 100, "publicaciones": 32821}
    respuesta["children_categories"] = [{"id": "x"}]
    assert mercado_categorias.leer_categoria({}, "MLA5232")["es_hoja"] is False
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (403, None))
    assert mercado_categorias.leer_categoria({}, "MLA5232") is None and mercado_categorias.leer_atributos({}, "MLA5232") is None


def test_la_muestra_solo_toma_productos_del_dominio_y_ofertas_de_esa_categoria(monkeypatch):
    pedidos = []

    def falso(ruta, headers, params=None, timeout=12):
        pedidos.append((ruta, dict(params or {})))
        if ruta == "/catalog_domains/MLA-DRILLS":
            return 200, {"name": "Taladros eléctricos"}
        if ruta == "/products/search":
            return 200, {"results": [{"id": "P1", "domain_id": "MLA-DRILLS"}, {"id": "P2", "domain_id": "MLA-OTRO"}, {"id": "P3", "domain_id": "MLA-DRILLS"}]}
        if ruta == "/products/P1/items":
            return 200, {"results": [_oferta(100, "A", categoria="MLA5232"), _oferta(900, "B", categoria="MLA777")]}
        if ruta == "/products/P3/items":
            return 200, {"results": [_oferta(300, "C", categoria="MLA5232")]}
        raise AssertionError(ruta)
    monkeypatch.setattr(mercado_categorias, "_get", falso)
    m = rel.tomar_muestra(rel.Cliente("t"), {"category_id": "MLA5232", "dominio_id": "MLA-DRILLS", "es_hoja": True})
    assert m["muestra_productos"] == 2 and m["muestra_ofertas"] == 2 and m["precio_min"] == 100.0 and m["precio_max"] == 300.0
    busqueda = next(p for r, p in pedidos if r == "/products/search")
    assert busqueda["q"] == "Taladros eléctricos" and busqueda["domain_id"] == "MLA-DRILLS" and busqueda["status"] == "active"
    assert not any(r == "/products/P2/items" for r, _ in pedidos)                    # un producto de otro dominio no se mira


def test_no_hay_muestra_sin_dominio_ni_en_categorias_que_no_son_hoja():
    assert rel.tomar_muestra(rel.Cliente("t"), {"category_id": "MLA1", "dominio_id": None, "es_hoja": True}) is None
    assert rel.tomar_muestra(rel.Cliente("t"), {"category_id": "MLA1", "dominio_id": "MLA-X", "es_hoja": False}) is None


def test_se_interpreta_una_palabra_con_los_atributos_que_extrae_mercado_libre(monkeypatch):
    respuesta = [{"category_id": "MLA1055", "domain_id": "MLA-CELLPHONES", "domain_name": "Celulares",
                  "attributes": [{"id": "BRAND", "name": "Marca", "value_id": "9344", "value_name": "Apple"}, {"id": "INTERNAL_MEMORY", "name": "Memoria interna", "value_id": "84611", "value_name": "128 GB"}]}]
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (200, respuesta))
    assert rel.interpretar_palabra(rel.Cliente("t"), "iphone 15 128 gb") == {
        "categoria_id": "MLA1055", "dominio_id": "MLA-CELLPHONES",
        "atributos": [{"id": "BRAND", "name": "Marca", "value_id": "9344", "value_name": "Apple"}, {"id": "INTERNAL_MEMORY", "name": "Memoria interna", "value_id": "84611", "value_name": "128 GB"}]}
    respuesta.clear()
    assert rel.interpretar_palabra(rel.Cliente("t"), "algo raro") == {}              # entendió «nada»: se guarda así y no se vuelve a pedir
    monkeypatch.setattr(mercado_categorias, "_get", lambda ruta, headers, params=None, timeout=12: (500, None))
    assert rel.interpretar_palabra(rel.Cliente("t"), "x") is None                    # no respondió: se reintenta otro día


def test_el_token_de_aplicacion_se_pide_con_client_credentials_y_no_se_guarda(monkeypatch):
    enviado = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "tok-app", "expires_in": 21600}

    def falso_post(url, **kw):
        enviado.update(url=url, **kw)
        return Resp()
    monkeypatch.setattr(rel.meli_http, "post", falso_post)
    assert rel.obtener_token_aplicacion() == "tok-app"
    assert enviado["url"].endswith("/oauth/token") and enviado["data"]["grant_type"] == "client_credentials"
    Resp.status_code = 401
    assert rel.obtener_token_aplicacion() is None


# ── Scheduler ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_scheduler_corre_el_relevamiento_cada_hora_y_unos_minutos_despues_de_arrancar():
    fuente = open(os.path.join(RAIZ, "scheduler.py"), encoding="utf-8").read()
    assert re.search(r'add_job\(_tarea_relevar_mercado, "interval", hours=1, id="relevar_mercado", max_instances=1, coalesce=True,\s*next_run_time=', fuente)


def test_la_tarea_no_arranca_antes_de_las_4_de_argentina(monkeypatch):
    import scheduler
    llamadas = []
    monkeypatch.setattr(scheduler.mercado_relevador, "relevar_si_falta", lambda: llamadas.append(1) or {"ok": True})

    class Reloj:
        hora = 3

        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 10, cls.hora, 30, tzinfo=timezone.utc)
    import datetime as modulo
    monkeypatch.setattr(modulo, "datetime", Reloj)
    scheduler._tarea_relevar_mercado()
    assert llamadas == []
    Reloj.hora = 7
    scheduler._tarea_relevar_mercado()
    assert llamadas == [1]


# ── Una corrida completa contra el esquema real (siempre revertida) ──────────────────────────────────────────────────────────────────────
class _Revertir(Exception):
    pass


def _mercado_falso(listas):
    """Un Mercado Libre inventado, igual para cualquier categoría. `listas` es un dict mutable {'MLA': [...], 'defecto': [...]} con las palabras del día."""

    def falso(ruta, headers, params=None, timeout=12):
        raices = [f"MLA{i}" for i in range(1, 13)]
        if ruta == "/sites/MLA/categories":
            return 200, [{"id": r, "name": f"Raíz {r}"} for r in raices]
        if ruta.startswith("/trends/"):
            clave = ruta.rsplit("/", 1)[-1]
            return 200, [{"keyword": p, "url": "x"} for p in listas.get(clave, listas["defecto"])]
        if ruta.endswith("/attributes"):
            return 200, [{"id": "COLOR", "tags": {"allow_variations": True}}, {"id": "INTERNAL_MEMORY", "tags": {}}, {"id": "GTIN", "tags": {"hidden": True}}]
        if ruta.startswith("/categories/"):
            cid = ruta.rsplit("/", 1)[-1]
            raiz = cid in raices
            camino = [{"id": cid, "name": f"Raíz {cid}"}] if raiz else [{"id": "MLA1", "name": "Raíz MLA1"}, {"id": cid, "name": f"Hoja {cid}"}]
            return 200, {"id": cid, "name": camino[-1]["name"], "path_from_root": camino, "children_categories": [{"id": "h"}] if raiz else [],
                         "settings": {"catalog_domain": None if raiz else "MLA-PRUEBA", "max_title_length": 60, "max_variations_allowed": 100}, "total_items_in_this_category": 5000 + len(cid)}
        if ruta == "/sites/MLA/domain_discovery/search":
            return 200, [{"category_id": "MLA1055", "domain_id": "MLA-CELLPHONES", "attributes": [{"id": "BRAND", "name": "Marca", "value_id": "1", "value_name": "Apple"}]}]
        if ruta == "/catalog_domains/MLA-PRUEBA":
            return 200, {"name": "Dominio de prueba"}
        if ruta == "/products/search":
            return 200, {"results": [{"id": "P1", "domain_id": "MLA-PRUEBA"}, {"id": "P2", "domain_id": "MLA-PRUEBA"}]}
        if ruta.startswith("/products/"):
            return 200, {"results": [_oferta(1000, "A", categoria="MLA_PRUEBA_HOJA"), _oferta(3000, "B", categoria="MLA_PRUEBA_HOJA")]}
        raise AssertionError(f"pedido inesperado: {ruta}")
    return falso


@contextmanager
def _admin_sin_commit(conexion):
    """Reemplaza `db.conexion_admin` por una conexión única que no confirma nada: lo que escribe el relevador queda en la transacción de la prueba."""
    class Envoltorio:
        def cursor(self):
            return conexion.cursor()

    class Falsa:
        def __call__(self):
            return self

        def __enter__(self):
            return Envoltorio()

        def __exit__(self, *a):
            return False
    yield Falsa()


@CON_BASE
def test_una_corrida_completa_guarda_la_historia_dia_a_dia_y_es_repetible(monkeypatch):
    import psycopg

    import config
    import db
    listas = {"defecto": ["zzz prueba uno", "ZZZ prueba dos", "zzz prueba uno"], "MLA": ["zzz prueba dos", "zzz prueba uno"]}
    monkeypatch.setattr(mercado_categorias, "_get", _mercado_falso(listas))
    monkeypatch.setattr(rel, "obtener_token_aplicacion", lambda: "token-de-prueba")
    d1 = date(2030, 1, 10)
    resultado = {}
    con = psycopg.connect(config.DATABASE_URL_ADMIN)
    try:
        cur = con.cursor()
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
        cuenta = cur.fetchone()[0]
        cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, estado, category_id) VALUES (%s, 'MLA_PRUEBA_RELEVADOR', 'x', 'active', 'MLA_PRUEBA_HOJA')", (cuenta,))
        with _admin_sin_commit(con) as falsa:
            monkeypatch.setattr(db, "conexion_admin", falsa)
            r1 = rel.relevar(d1)
            cur.execute("SELECT count(*) FROM mercado_categoria_diaria WHERE fecha = %s", (d1,))
            filas_dia_1 = cur.fetchone()[0]
            r1_repetida = rel.relevar(d1)
            cur.execute("SELECT count(*) FROM mercado_categoria_diaria WHERE fecha = %s", (d1,))
            filas_tras_repetir = cur.fetchone()[0]
            cur.execute("SELECT racha_dias, dias_en_lista, mejor_posicion, posicion_actual FROM mercado_keyword_estado e JOIN mercado_keywords k ON k.id = e.keyword_id WHERE e.category_id = 'MLA_PRUEBA_HOJA' AND k.texto = 'zzz prueba uno'")
            resultado["dia1"] = cur.fetchone()
            r2 = rel.relevar(d1 + timedelta(days=1))
            cur.execute("SELECT racha_dias, dias_en_lista FROM mercado_keyword_estado e JOIN mercado_keywords k ON k.id = e.keyword_id WHERE e.category_id = 'MLA_PRUEBA_HOJA' AND k.texto = 'zzz prueba uno'")
            resultado["dia2"] = cur.fetchone()
            listas["defecto"] = ["zzz prueba dos"]                                                  # el día 3 «uno» sale de la lista
            rel.relevar(d1 + timedelta(days=2))
            cur.execute("SELECT racha_dias, dias_en_lista, posicion_actual FROM mercado_keyword_estado e JOIN mercado_keywords k ON k.id = e.keyword_id WHERE e.category_id = 'MLA_PRUEBA_HOJA' AND k.texto = 'zzz prueba uno'")
            resultado["dia3"] = cur.fetchone()
            cur.execute("SELECT posicion_actual, racha_dias FROM mercado_keyword_estado e JOIN mercado_keywords k ON k.id = e.keyword_id WHERE e.category_id = 'MLA_PRUEBA_HOJA' AND k.texto = 'zzz prueba dos'")
            resultado["dia3_dos"] = cur.fetchone()
        cur.execute("SELECT keywords FROM mercado_tendencias_diaria WHERE category_id = 'MLA_PRUEBA_HOJA' AND fecha = %s", (d1,))
        resultado["lista_dia1"] = len(cur.fetchone()[0])
        cur.execute("SELECT texto, categoria_id, dominio_id, atributos FROM mercado_keywords WHERE texto LIKE 'zzz prueba%' ORDER BY texto")
        resultado["palabras"] = cur.fetchall()
        cur.execute("SELECT seguida, atributos_variacion, atributos_ocultos, dominio_id, es_hoja, publicaciones FROM mercado_categorias WHERE category_id = 'MLA_PRUEBA_HOJA'")
        resultado["hoja"] = cur.fetchone()
        cur.execute("SELECT muestra_productos, muestra_ofertas, precio_min, precio_p50, precio_max, publicaciones FROM mercado_categoria_diaria WHERE category_id = 'MLA_PRUEBA_HOJA' AND fecha = %s", (d1,))
        resultado["muestra"] = cur.fetchone()
        cur.execute("SELECT count(*) FROM mercado_categorias WHERE cardinality(camino) = 1 AND seguida")
        resultado["raices_seguidas"] = cur.fetchone()[0]
        cur.execute("SELECT count(*), count(*) FILTER (WHERE fin IS NOT NULL), max(llamadas) FROM mercado_relevamientos WHERE tipo = 'diario' AND fecha = %s", (d1,))
        resultado["registro"] = cur.fetchone()
        resultado["r"] = (r1, r1_repetida, r2, filas_dia_1, filas_tras_repetir)
        raise _Revertir()
    except _Revertir:
        pass
    finally:
        con.rollback()
        con.close()
    r1, r1_repetida, r2, filas_dia_1, filas_tras_repetir = resultado["r"]
    assert r1["categorias"] >= 14 and r1["con_tendencias"] == r1["categorias"] and r1["errores"] == 0, r1       # 12 raíces + la lista general + la hoja de prueba (+ las reales de la base)
    assert r1["palabras_nuevas"] == 2 and r1["interpretadas"] == 2 and r1["atributos"] >= 1 and r1["muestras"] >= 1
    assert filas_tras_repetir == filas_dia_1                                                                       # repetir el día no duplica filas
    assert r1_repetida["palabras_nuevas"] == 0 and r2["palabras_nuevas"] == 0
    assert resultado["lista_dia1"] == 2                                                                            # sin repetidas ni vacías
    assert resultado["dia1"] == (1, 1, 1, 1)                                                                       # «uno»: puesto 1, primer día (la repetición del día no sumó)
    assert resultado["dia2"] == (2, 2)                                                                             # al día siguiente: racha 2
    assert resultado["dia3"] == (2, 2, None)                                                                       # salió: conserva su historia, ya no tiene puesto
    assert resultado["dia3_dos"] == (1, 3)                                                                         # «dos» subió al puesto 1 y lleva 3 días
    assert [p[0] for p in resultado["palabras"]] == ["zzz prueba dos", "zzz prueba uno"]
    assert all(p[1] == "MLA1055" and p[2] == "MLA-CELLPHONES" and p[3][0]["value_name"] == "Apple" for p in resultado["palabras"])
    seguida, variacion, ocultos, dominio, hoja, publicaciones = resultado["hoja"]
    assert seguida and variacion == ["COLOR"] and ocultos == ["GTIN"] and dominio == "MLA-PRUEBA" and hoja and publicaciones == 5000 + len("MLA_PRUEBA_HOJA")
    assert resultado["muestra"][:5] == (2, 4, 1000, 2000, 3000)                                                    # 2 productos × 2 ofertas de 1000 y 3000
    assert resultado["raices_seguidas"] >= 12
    assert resultado["registro"][0] == 2 and resultado["registro"][1] == 2 and resultado["registro"][2] > 14


@CON_BASE
def test_si_hoy_ya_hubo_un_relevamiento_completo_no_se_repite(monkeypatch):
    import psycopg

    import config
    import db
    corridas = []
    monkeypatch.setattr(rel, "relevar", lambda fecha=None: corridas.append(fecha) or {"ok": True})
    d = date(2031, 3, 4)
    con = psycopg.connect(config.DATABASE_URL_ADMIN)
    try:
        cur = con.cursor()
        with _admin_sin_commit(con) as falsa:
            monkeypatch.setattr(db, "conexion_admin", falsa)
            assert rel.relevar_si_falta(d) == {"ok": True}                                                    # no había nada: corre
            cur.execute("INSERT INTO mercado_relevamientos (tipo, fecha, fin) VALUES ('diario', %s, now())", (d,))
            assert rel.relevar_si_falta(d) is None                                                           # ya terminó: no
            assert rel.relevar_si_falta(d + timedelta(days=1)) == {"ok": True}                              # otro día: corre
            cur.execute("INSERT INTO mercado_relevamientos (tipo, fecha) VALUES ('diario', %s)", (d + timedelta(days=5),))
            assert rel.relevar_si_falta(d + timedelta(days=5)) is None                                       # empezó hace un momento y sigue en marcha: no
            cur.execute("UPDATE mercado_relevamientos SET inicio = now() - interval '3 hours' WHERE fecha = %s", (d + timedelta(days=5),))
            assert rel.relevar_si_falta(d + timedelta(days=5)) == {"ok": True}                              # quedó colgada hace 3 horas: se reintenta
    finally:
        con.rollback()
        con.close()
    assert corridas == [d, d + timedelta(days=1), d + timedelta(days=5)]

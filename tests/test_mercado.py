"""
Pantalla Mercado (mercado.py, /mercado): búsquedas en alza y oferta de las categorías, leídas de las tablas globales del relevador.
Lo que más importa: nada se inventa (sin dato no es cero, una búsqueda que ya estaba al empezar a medir no es «nueva»), el texto de Mercado Libre se escapa, y una cuenta nunca ve las
publicaciones de otra al marcar «tenés publicaciones con esto». Los casos con la base corren dentro de una transacción que se revierte.
"""
import os
from datetime import date

import pytest

import mercado

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not (os.getenv("DATABASE_URL") and os.getenv("DATABASE_URL_ADMIN")), reason="Sin DATABASE_URL/DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


# ── Puro: coincidencia con tus publicaciones ───────────────────────────────────────────────────────────────────────────────────────────

def _titulos(*titulos):
    return [mercado.tokens_de(t) for t in titulos]


def test_una_busqueda_coincide_con_las_publicaciones_que_tienen_todas_sus_palabras():
    titulos = _titulos("Campera Pluma Mujer Impermeable", "Campera De Jean Hombre", "Chaleco Inflable Mujer")
    assert mercado.publicaciones_con_busqueda("campera pluma", titulos) == 1
    assert mercado.publicaciones_con_busqueda("camperas", titulos) == 2                 # plural y singular: «camperas» es «campera»
    assert mercado.publicaciones_con_busqueda("campera de cuero hombres", titulos) == 0   # le falta «cuero»
    assert mercado.publicaciones_con_busqueda("CAMPERA   PLUMA", titulos) == 1          # mayúsculas y espacios no cuentan


def test_una_busqueda_de_palabras_genericas_no_coincide_con_nada():
    titulos = _titulos("Campera Mujer", "Buzo Hombre", "Remera Unisex")
    assert mercado.publicaciones_con_busqueda("mujer", titulos) == 0                    # «mujer» está en medio catálogo: no distingue un producto
    assert mercado.publicaciones_con_busqueda("hombre premium", titulos) == 0
    assert mercado.publicaciones_con_busqueda("", titulos) == 0 and mercado.publicaciones_con_busqueda("campera", []) == 0


def test_los_acentos_no_separan_la_misma_palabra():
    assert mercado.publicaciones_con_busqueda("camión", _titulos("Camion de juguete")) == 1


# ── Puro: movimiento de una búsqueda ───────────────────────────────────────────────────────────────────────────────────────────────────

D = date


def test_el_movimiento_compara_con_el_puesto_de_hace_una_semana():
    assert mercado.estado_busqueda(3, 9, D(2026, 10, 1), D(2026, 10, 20), D(2026, 10, 1)) == ("sube", "Subió 6 puestos en la semana")
    assert mercado.estado_busqueda(5, 4, D(2026, 10, 1), D(2026, 10, 20), D(2026, 10, 1)) == ("baja", "Bajó 1 puesto en la semana")
    assert mercado.estado_busqueda(5, 5, D(2026, 10, 1), D(2026, 10, 20), D(2026, 10, 1))[0] == "igual"


def test_una_busqueda_que_ya_estaba_al_empezar_a_medir_no_es_nueva():
    # primer día de historia: todas las búsquedas «entran» ese día, pero no se sabe desde cuándo están → nada que decir
    assert mercado.estado_busqueda(1, None, D(2026, 10, 13), D(2026, 10, 13), D(2026, 10, 13)) is None
    assert mercado.estado_busqueda(1, None, D(2026, 10, 13), D(2026, 10, 18), D(2026, 10, 13)) is None


def test_una_busqueda_que_entro_despues_de_empezar_a_medir_es_nueva_solo_esa_semana():
    assert mercado.estado_busqueda(7, None, D(2026, 10, 16), D(2026, 10, 18), D(2026, 10, 13)) == ("nueva", "Entró esta semana")
    assert mercado.estado_busqueda(7, None, D(2026, 10, 16), D(2026, 10, 30), D(2026, 10, 13)) is None       # ya pasó la semana: no es noticia


# ── Puro: variación de la oferta y concentración ───────────────────────────────────────────────────────────────────────────────────────

def test_la_variacion_usa_el_dato_mas_reciente_con_la_antiguedad_pedida_y_sin_historia_no_inventa():
    serie = [(D(2026, 10, 14), 1100), (D(2026, 10, 13), 1090), (D(2026, 10, 7), 1000), (D(2026, 9, 1), 800)]
    assert mercado._variacion(serie, 7) == {"diferencia": 100, "pct": 10.0, "desde": D(2026, 10, 7)}
    assert mercado._variacion(serie, 30)["pct"] == 37.5 and mercado._variacion(serie, 30)["desde"] == D(2026, 9, 1)
    assert mercado._variacion(serie, 90) is None                          # no hay un dato de hace 90 días
    assert mercado._variacion([(D(2026, 10, 14), 1100)], 7) is None       # un solo día: nada que comparar
    assert mercado._variacion([(D(2026, 10, 14), 5), (D(2026, 10, 1), 0)], 7) is None      # contra cero no hay porcentaje


def test_la_concentracion_se_lee_con_umbrales_conocidos():
    assert mercado.etiqueta_concentracion(None) is None
    assert mercado.etiqueta_concentracion(900)[0] == "baja" and mercado.etiqueta_concentracion(1500)[0] == "media" and mercado.etiqueta_concentracion(2500)[0] == "alta"


# ── Con la base ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _sembrar(cur, p):
    """Una raíz y una hoja seguidas, tres búsquedas (una interpretada por Mercado Libre) y dos días de historia, más la cuenta con publicaciones en la hoja."""
    raiz, hoja, otra = f"MLA9{p}1", f"MLA9{p}2", f"MLA9{p}3"
    cur.execute("INSERT INTO mercado_categorias (category_id, nombre, camino, camino_nombres, publicaciones, seguida, es_hoja) VALUES (%s, 'Ropa prueba', ARRAY[%s], ARRAY['Ropa prueba'], 1000000, true, false)", (raiz, raiz))
    cur.execute("INSERT INTO mercado_categorias (category_id, nombre, parent_id, camino, camino_nombres, publicaciones, seguida, es_hoja) VALUES (%s, 'Camperas prueba', %s, ARRAY[%s, %s], ARRAY['Ropa prueba', 'Camperas prueba'], 50000, true, true)", (hoja, raiz, raiz, hoja))
    cur.execute("INSERT INTO mercado_categorias (category_id, nombre, camino, camino_nombres, publicaciones, seguida, es_hoja) VALUES (%s, 'Otra prueba', ARRAY[%s], ARRAY['Otra prueba'], 10, true, true)", (otra, otra))
    ids = []
    # cada búsqueda lleva una marca propia (za/zb/zc + el pid) para no chocar con las reales (texto es único); solo la de la campera pluma está en el título de la publicación de prueba
    for texto, categoria in ((f"campera pluma za{p}", hoja), (f"campera <script>x</script> zb{p}", hoja), (f"mujer zc{p}", hoja)):
        cur.execute("INSERT INTO mercado_keywords (texto, categoria_id, atributos) VALUES (%s, %s, %s::jsonb) RETURNING id", (texto, categoria, '[{"name": "Marca", "value_name": "Columbia"}, {"name": "Tipo de ancho", "value_name": "Estándar"}]'))
        ids.append(cur.fetchone()[0])
    cur.execute("INSERT INTO mercado_tendencias_diaria (category_id, fecha, keywords) VALUES (%s, DATE '2030-05-01', %s), (%s, DATE '2030-05-10', %s)", (hoja, ids[:2], hoja, ids))
    # estado: «campera pluma» ya estaba desde el primer día y hace 7 días era la 5ª (sube 3); la 3ª entró el 10/05 (nueva)
    cur.execute("""INSERT INTO mercado_keyword_estado (category_id, keyword_id, primera_vez, ultima_vez, racha_dias, dias_en_lista, mejor_posicion, posicion_actual, posicion_hace_7d)
                   VALUES (%s, %s, DATE '2030-05-01', DATE '2030-05-10', 10, 10, 2, 2, 5), (%s, %s, DATE '2030-05-01', DATE '2030-05-10', 10, 10, 1, 1, NULL), (%s, %s, DATE '2030-05-10', DATE '2030-05-10', 1, 1, 3, 3, NULL)""",
                (hoja, ids[0], hoja, ids[1], hoja, ids[2]))
    cur.execute("INSERT INTO mercado_categoria_diaria (category_id, fecha, publicaciones) VALUES (%s, DATE '2030-05-01', 40000), (%s, DATE '2030-05-10', 50000), (%s, DATE '2030-05-10', 1000000)", (hoja, hoja, raiz))
    cur.execute("""INSERT INTO mercado_categoria_diaria (category_id, fecha, publicaciones, muestra_productos, muestra_ofertas, muestra_vendedores, precio_p25, precio_p50, precio_p75, pct_full, pct_envio_gratis,
                                                         concentracion_top3, hhi, muestra_alcance) VALUES (%s, DATE '2030-05-09', 49000, 12, 80, 30, 40000, 52000, 70000, 45.5, 60, 38.1, 1700, 'categoria')""", (hoja,))
    return raiz, hoja, otra


@CON_BASE
def test_la_pantalla_arma_busquedas_ficha_y_comparacion_con_datos_reales_y_sin_inventar():
    import db
    cuenta, _ = _cuenta_y_usuario()
    p = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            raiz, hoja, otra = _sembrar(cur, p)
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, category_id) VALUES (%s, %s, %s, 1, 'active', %s)", (cuenta, f"PRUEBA-MER-{p}", f"Campera Pluma Mujer Negra za{p}", hoja))
            datos = mercado.armar_pantalla(cur, cuenta, hoja)
            assert datos["elegida"] == hoja and datos["ids_propias"] >= {hoja}
            ficha = datos["ficha"]
            assert ficha["publicaciones"] == 50000 and ficha["peso_rubro"] == {"nombre": "Ropa prueba", "pct": 5.0}      # 50.000 de 1.000.000
            assert ficha["variacion_7"]["diferencia"] == 10000 and ficha["variacion_7"]["pct"] == 25.0                     # 40.000 el 1/05 → 50.000 el 10/05
            assert ficha["muestra"]["precio_p50"] == 52000 and ficha["muestra"]["concentracion"][0] == "media" and not ficha["muestra"]["vacia"]
            por_texto = {b["texto"]: b for b in datos["busquedas_ficha"]}
            pluma = por_texto[f"campera pluma za{p}"]
            assert pluma["posicion"] == 2 and pluma["movimiento"] == ("sube", "Subió 3 puestos en la semana") and pluma["racha"] == 10
            assert pluma["entiende"] == ["Columbia"] and pluma["tus_publicaciones"] == 1                                    # «Estándar» no se muestra; la cuenta tiene una campera pluma
            assert por_texto[f"mujer zc{p}"]["movimiento"] == ("nueva", "Entró esta semana") and por_texto[f"mujer zc{p}"]["tus_publicaciones"] == 0
            assert por_texto[f"campera <script>x</script> zb{p}"]["movimiento"] is None                                   # ya estaba el primer día: no se sabe desde cuándo
            tuyas = [b for b in datos["busquedas_tuyas"] if b["texto"].endswith(f"{p}")]
            assert [b["posicion"] for b in tuyas] == [1, 2, 3] and all(b["categoria_nombre"] == "Camperas prueba" for b in tuyas)
            comparacion = {c["category_id"]: c for c in datos["seguidas"]}
            assert comparacion[hoja]["precio_p50"] == 52000 and comparacion[hoja]["busquedas"] == 3 and comparacion[otra]["precio_p50"] is None      # sin muestra queda None, no 0
            raise _Revertir()
    except _Revertir:
        pass


def _cuenta_y_usuario():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT id, usuario_id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


@CON_BASE
def test_las_publicaciones_de_otra_cuenta_no_cuentan_como_tuyas():
    import db
    cuenta, _ = _cuenta_y_usuario()
    p = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            _, hoja, _ = _sembrar(cur, p)
            cur.execute("SELECT id FROM cuentas_meli WHERE id <> %s ORDER BY id LIMIT 1", (cuenta,))
            otra = cur.fetchone()
            if not otra:
                pytest.skip("Hace falta una segunda cuenta para probar el aislamiento")
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, category_id) VALUES (%s, %s, %s, 1, 'active', %s)", (otra[0], f"PRUEBA-AJ-{p}", f"Campera Pluma Ajena za{p}", hoja))   # coincidiría con la búsqueda si se mezclaran las cuentas
            datos = mercado.armar_pantalla(cur, cuenta, hoja)
            pluma = next(b for b in datos["busquedas_ficha"] if b["texto"] == f"campera pluma za{p}")
            assert hoja not in datos["ids_propias"] and pluma["tus_publicaciones"] == 0
            raise _Revertir()
    except _Revertir:
        pass


@CON_BASE
def test_una_categoria_que_no_se_releva_o_con_formato_raro_cae_en_la_de_la_cuenta():
    import db
    cuenta, _ = _cuenta_y_usuario()
    p = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            _, hoja, _ = _sembrar(cur, p)
            for pedida in ("'; DROP TABLE x;--", "MLA", "MLA00000000", "../etc"):
                datos = mercado.armar_pantalla(cur, cuenta, pedida)
                assert datos["elegida"] != pedida
            raise _Revertir()
    except _Revertir:
        pass


# ── La plantilla ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def renderizar():
    pytest.importorskip("flask")
    if not os.getenv("DATABASE_URL"):
        pytest.skip("Sin DATABASE_URL: importar app abre el pool")
    import app as modulo_app
    from flask import render_template

    def _render(**contexto):
        with modulo_app.app.test_request_context("/mercado"):
            return render_template("mercado.html", active_nav="mercado", **contexto)
    return _render


def _datos(**cambios):
    base = {
        "cobertura": {"desde": date(2030, 5, 1), "hasta": date(2030, 5, 10), "dias": 10, "categorias": 3},
        "propias": [{"category_id": "MLA1", "nombre": "Camperas", "camino": [], "activas": 4, "publicaciones": 50000, "dominio_id": None, "relevada": True}],
        "seguidas": [{"category_id": "MLA1", "nombre": "Camperas", "camino": ["Ropa", "Camperas"], "es_hoja": True, "publicaciones": 50000, "precio_p50": 52000, "pct_full": 45.5, "pct_envio_gratis": 60,
                      "hhi": 1700, "muestra_ofertas": 80, "busquedas": 2, "concentracion": ("media", "Algo concentrada")}],
        "busquedas_tuyas": [{"texto": "campera <script>alert(1)</script>", "posicion": 1, "movimiento": ("sube", "Subió 2 puestos en la semana"), "racha": 5, "entiende": ["Columbia"],
                             "categoria_nombre": "Camperas", "tus_publicaciones": 2}],
        "sin_relevar": [], "elegida": "MLA1", "ids_propias": {"MLA1"},
        "ficha": {"category_id": "MLA1", "nombre": "Camperas", "camino_nombres": ["Ropa", "Camperas"], "es_hoja": True, "publicaciones": 50000, "variacion_7": {"diferencia": 5000, "pct": 11.1, "desde": date(2030, 5, 3)},
                  "variacion_30": None, "peso_rubro": {"nombre": "Ropa", "pct": 5.0},
                  "muestra": {"fecha": date(2030, 5, 9), "productos": 12, "ofertas": 80, "vendedores": 30, "precio_p25": 40000, "precio_p50": 52000, "precio_p75": 70000, "pct_full": 45.5,
                              "pct_envio_gratis": 60, "pct_tienda_oficial": 10, "pct_con_descuento": 22, "concentracion_top3": 38.1, "alcance": "categoria", "concentracion": ("media", "Algo concentrada"), "vacia": False}},
        "busquedas_ficha": [{"texto": "campera pluma", "posicion": 2, "movimiento": None, "racha": None, "entiende": [], "tus_publicaciones": 0}],
    }
    base.update(cambios)
    return base


def test_la_pantalla_muestra_cada_dato_con_su_origen_y_escapa_lo_que_viene_de_mercado_libre(renderizar):
    html = renderizar(**_datos())
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Real · lista de Mercado Libre" in html and "Real · subió 11,1 % en 7 días" in html and "Calculado · de las publicaciones de Ropa" in html
    assert "Tenés 2 publicaciones" in html and "Sin publicación tuya con esto" in html and "Subió 2 puestos en la semana" in html and "5 días seguidos" in html
    assert "$52.000" in html and "ni cuánto vende cada competidor" in html                                                 # lo que Mercado Libre NO informa, dicho de entrada


def test_sin_muestra_de_precios_se_dice_en_vez_de_mostrar_ceros(renderizar):
    ficha = {**_datos()["ficha"], "muestra": None, "variacion_7": None}
    html = renderizar(**_datos(ficha=ficha))
    assert "No hay precios medidos en esta categoría" in html and "la historia todavía no alcanza" in html
    assert "la mitad cuesta menos" not in html and "Competencia</div>" not in html            # ni precio ni competencia inventados


def test_sin_datos_de_mercado_la_pantalla_lo_explica(renderizar):
    html = renderizar(**_datos(seguidas=[], ficha=None, busquedas_tuyas=[], busquedas_ficha=[], elegida=None))
    assert "Todavía no hay datos de mercado" in html


def test_el_menu_tiene_mercado_en_crecimiento_y_el_buscador_lo_conoce():
    import nav_config
    assert any(p["nav_key"] == "mercado" for p in nav_config.GRUPOS_NAV["crecimiento"]["paginas"])
    assert "'/mercado'" in open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()


def test_mercado_no_llama_a_mercado_libre():
    """La pantalla lee solo la base: sin token, sin red (así abre rápido y no gasta pedidos)."""
    fuente = open(os.path.join(RAIZ, "mercado.py"), encoding="utf-8").read()
    assert "import requests" not in fuente and "meli_http" not in fuente and "token_manager" not in fuente

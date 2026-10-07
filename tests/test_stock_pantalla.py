"""
Pantalla de Stock: el aviso y "lo que tenés que reponer" vienen ya armados en la página (antes llegaban por un fetch y la pantalla parpadeaba), los filtros nuevos
y la columna "Alcanza para". Se renderiza la plantilla con datos armados a mano (la app real, sin tocar la base).
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402

STATS = {"activas": 3, "valor_total": "300.000,00", "propio": 20, "full": 5}
SIN_FULL = {"total": 0, "items": []}


def _modelo(titulo, propio, full, estado="active", dias=None, texto="—", tono="neutral", ritmo=0):
    return {
        "id": "MLA" + str(abs(hash(titulo)) % 10**6), "titulo": titulo, "precio": 10000, "precio_rango": "10.000", "precio_formateado": "10.000", "descuento_pct": None,
        "precio_original_formateado": None, "recibis_formateado": None, "estado": estado, "thumbnail": None, "stock_propio": propio, "stock_full": full,
        "variantes": [{"id_meli": "MLAV", "talle": "M", "propio": propio, "full": full, "revisar_duplicado": False}],
        "sparkline_total_7d": 0, "sparkline_puntos": "0,12 70,12", "unidades_ritmo": ritmo, "dias_stock": dias, "dias_stock_texto": texto, "dias_stock_tono": tono,
    }


def _riesgo(titulo, talle="M", dias=2.0, stock=4, proveedor=None, pedir_ya=False):
    return {"id_variante": "V1", "id_meli": "MLA1", "titulo": titulo, "talle": talle, "color": None, "stock_total": stock, "velocidad_diaria": 2.0, "dias_restantes": dias,
            "proveedor_nombre": proveedor, "tiempo_entrega_dias": 7 if proveedor else None, "dias_para_pedir": -1 if pedir_ya else 3, "pedir_ya": pedir_ya}


def _render(productos, riesgo, en_riesgo=()):
    with aplicacion.app.test_request_context("/"):
        return aplicacion.render_template("index.html", productos=productos, stats=STATS, full_no_disponible=SIN_FULL, reactivables=[], riesgo=riesgo,
                                          modelos_en_riesgo=set(en_riesgo), active_nav="stock")


def test_el_aviso_de_riesgo_viene_en_la_pagina_sin_esperar_a_un_fetch():
    productos = [_modelo("Campera Jean", 4, 0, dias=2.0, texto="~2 días", tono="danger", ritmo=28), _modelo("Remera Lisa", 30, 0, dias=60, texto="~60 días", ritmo=7)]
    html = _render(productos, [_riesgo("Campera Jean")], {"Campera Jean"})
    assert "1 talle</b> se agota pronto" in html                     # singular: «1 talle se agota», no «1 talles se agotan»
    assert 'id="bloque-reponer"' in html and "Lo que tenés que reponer" in html
    assert "/api/quiebre_stock" not in html and "skeleton" not in html.split('id="estado-stock"')[1].split('id="bloque-reponer"')[0]
    assert "Stock sano" not in html


def test_con_varios_talles_en_riesgo_el_aviso_va_en_plural():
    html = _render([_modelo("Campera Jean", 4, 0)], [_riesgo("Campera Jean", "M"), _riesgo("Campera Jean", "L")], {"Campera Jean"})
    assert "2 talles</b> se agotan pronto" in html


def test_la_lista_de_reponer_marca_lo_urgente_y_avisa_cuando_hay_que_pedir_ya():
    html = _render([_modelo("Campera Jean", 4, 0)], [_riesgo("Campera Jean", dias=1.0, proveedor="Taller Sur", pedir_ya=True), _riesgo("Remera", dias=4.0)], {"Campera Jean"})
    assert "Pedí YA a Taller Sur" in html
    assert html.count('class="ux-item-accion ux-danger"') == 1 and html.count('class="ux-item-accion ux-warn"') == 1       # el de pedir YA en rojo, el de 4 días en naranja
    assert "alcanzan ~<b>4 días</b>" in html


def test_menos_de_un_dia_no_dice_cero_dias():
    html = _render([_modelo("Campera Jean", 1, 0)], [_riesgo("Campera Jean", dias=0.4, stock=1)], {"Campera Jean"})
    assert "no alcanzan ni para 1 día" in html and "~0 días" not in html


def test_stock_sano_solo_se_dice_cuando_se_pudo_calcular_y_no_hay_nada_agotado():
    sano = _render([_modelo("Remera Lisa", 30, 0)], [])
    assert "Stock sano" in sano and 'id="bloque-reponer"' not in sano
    sin_saber = _render([_modelo("Remera Lisa", 30, 0)], None)            # el cálculo falló: no se afirma nada
    assert "Stock sano" not in sin_saber and "Se agota pronto" not in sin_saber


def test_con_publicaciones_agotadas_el_aviso_rojo_manda_y_no_se_dice_stock_sano():
    html = _render([_modelo("Buzo", 0, 0), _modelo("Remera Lisa", 30, 0)], [])
    assert "1 publicación activa sin stock</b>" in html and 'id="btn-ver-sin-stock"' in html
    assert "Stock sano" not in html


def test_los_filtros_nuevos_cuentan_modelos_y_las_filas_llevan_su_marca():
    productos = [_modelo("Campera Jean", 4, 0), _modelo("Remera Lisa", 30, 12), _modelo("Buzo", 5, 0)]
    html = _render(productos, [_riesgo("Campera Jean")], {"Campera Jean"})
    assert 'id="chip-riesgo"' in html and 'id="chip-full"' in html
    assert html.count('data-riesgo="1"') == 1 and html.count('data-full="1"') == 1
    # contador de cada chip: 1 modelo en riesgo, 1 con stock en FULL
    assert "Se agota pronto <span" in html and "Con stock en FULL <span" in html


def test_sin_calculo_de_riesgo_no_se_ofrece_el_filtro_de_se_agota_pronto():
    html = _render([_modelo("Remera Lisa", 30, 0)], None)
    assert 'id="chip-riesgo"' not in html


def test_la_columna_alcanza_para_muestra_los_dias_o_el_motivo_por_el_que_no_hay():
    productos = [_modelo("Campera Jean", 4, 0, dias=2.0, texto="~2 días", tono="danger", ritmo=28),
                 _modelo("Remera Lisa", 30, 0, dias=None, texto="—", tono="neutral", ritmo=0),
                 _modelo("Pausada", 9, 0, estado="paused")]
    html = _render(productos, [])
    assert "~2 días" in html and 'title="Al ritmo de las últimas 2 semanas (28 u. vendidas)"' in html
    assert "Sin ventas en las últimas 2 semanas: no hay ritmo para estimar" in html
    assert 'data-orden="2.0"' in html and 'data-orden=""' in html          # sin ritmo la celda queda vacía: se ordena siempre al final, sin importar el sentido
    assert '<span class="text-faint" title="Sin ventas en las últimas 2 semanas' in html            # y se ve como un guion, no como una etiqueta


def test_en_cuentas_sin_full_no_hay_filtro_de_full():
    productos = [_modelo("Remera Lisa", 30, 0)]
    html = _render(productos, [])
    assert 'id="chip-full"' not in html

"""
Ola 1 del plan de UX (PLAN_UX_200.md), lo que faltaba (2026-10-13):
  7  · Dashboard: «Facturado hoy» ya no se repite (está en el hero) y los 14 días dicen «Te queda» como el hero, sin volver a explicar la cuenta;
  10 · Día a día: el título de cada parte es un escalón menor que el de la página;
  45 · Día a día: el resumen de hoy con números, cada uno lleva a su parte;
  55 · Pausadas con stock: la acción aparece como una barra fija al marcar («Reactivar 3»);
  77 · Ganancia Real: el sello de conciliación sube al hero.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── 7. Dashboard ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_dashboard_no_repite_facturado_hoy_en_la_fila_de_numeros():
    html = _leer("templates", "dashboard_personalizable.html")
    assert 'id="kpi-facturado"' not in html and "'kpi-facturado'" not in html
    assert html.count(">Facturado hoy<") == 1                                                    # como rótulo, solo en el hero
    assert 'id="kpi-ventas"' in html and "_resumenDelDia" in html                                # «Ventas hoy» lleva el modelo que más vendió y la comparación con ayer
    assert "#kpis-dia .ux-kpi:first-child" not in _leer("static", "css", "ux.css")


def test_los_catorce_dias_dicen_te_queda_y_no_vuelven_a_explicar_la_cuenta():
    html = _leer("templates", "dashboard_personalizable.html")
    resumen = html[html.index('id="panel-pl-14d"'):html.index('id="pl-waterfall"')]
    assert "<summary>Resultado de los últimos 14 días</summary>" in resumen and "facturado − costos = margen" not in html
    assert 'class="stat-chip-label">Te queda</div>\n                <div class="pl-tile-valor skeleton" id="pl-margen"' in html.replace("\r\n", "\n")


# ── 10 y 45. Día a día ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_cada_parte_de_dia_a_dia_tiene_un_titulo_un_escalon_menor_que_el_de_la_pagina():
    assert ".dia-seccion h2.page-title { font-size: 1.5em; }" in _leer("static", "css", "ux.css")
    assert '<h1 class="page-title">' in _leer("templates", "dia.html") and '<h2 class="page-title">' in _leer("templates", "_dia_despacho.html")


def test_el_resumen_de_dia_a_dia_cuenta_las_preguntas_sin_responder_cuando_se_ve_esa_lista():
    preguntas = _leer("templates", "_dia_preguntas.html")
    assert "function resumenDelDia()" in preguntas and "if (!texto || _estado !== 'pendiente') return;" in preguntas
    assert re.search(r"resumenDelDia\(\);\s*renderEstado\(\);", preguntas)                          # se actualiza cada vez que se dibuja la lista
    assert 'id="resumen-preguntas-texto"' in _leer("templates", "dia.html")


# ── 55. Pausadas con stock ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_las_pausadas_con_stock_tienen_una_barra_fija_que_aparece_al_marcar():
    html = _leer("templates", "index.html")
    assert 'id="barra-reactivar"' in html and 'class="ux-barra-accion" id="barra-reactivar" style="display:none;"' in html
    assert "document.getElementById('barra-reactivar').style.display = n ? '' : 'none';" in html
    assert html.index('</details>\n<div class="ux-barra-accion" id="barra-reactivar"') > 0 or html.replace("\r\n", "\n").index('</details>\n<div class="ux-barra-accion" id="barra-reactivar"') > 0       # fuera del plegable: dentro no se pegaría al borde
    assert "'Marcar la publicación' if reactivables|length == 1 else 'Marcar las ' ~ reactivables|length" in html                 # «Marcar las 22», no «Marcar todas»


# ── 77. Ganancia Real ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_sello_de_conciliacion_esta_en_el_hero_y_lleva_a_la_explicacion():
    html = _leer("templates", "metricas.html").replace("\r\n", "\n")
    hero = html[html.index('<div class="ux-hero ux-{{ tono }}">'):html.index("<!-- A dónde se fue cada peso")]
    assert 'class="ux-hero-sello ux-{{ \'ok\' if cc_hero.coincide_pct >= 98 else \'warn\' }}" href="#conciliacion"' in hero
    assert "de coincidencia con lo que Mercado Libre te depositó" in hero
    assert 'id="conciliacion"' in html and "cc_hero.coincide_pct is not none" in hero                    # sin dato de conciliación no se muestra un sello vacío
    assert ".ux-hero-sello {" in _leer("static", "css", "ux.css")

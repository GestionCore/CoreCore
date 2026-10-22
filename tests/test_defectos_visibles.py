"""
Defectos visibles de la ola 1 del plan de UX (PLAN_UX_200.md), medidos en la app real el 2026-10-12:
  · los montos de las tarjetas KPI se partían en dos líneas («$1.040.7 / 35») porque la tarjeta era angosta y el número tenía tamaño fijo;
  · la pastilla de variación llegaba a 9,5 px dentro de un subtítulo chico;
  · Precios mostraba «✓ Todos tus precios cubren tu margen» con 30 de 70 publicaciones analizadas (40 sin calcular): una falsa tranquilidad;
  · Publicidad mostraba «Contra el período anterior (—)» porque pasaba las fechas en dd/mm a una función que espera ISO;
  · la misma pantalla se llamaba «Calculadora MeLi» en la pestaña y «Calculadora de comisiones» en el título.
"""
import os
import re
from datetime import date

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── Montos que no se parten y letra que se lee ──────────────────────────────────────────────────────────────────────────────

def _regla(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_el_monto_de_un_kpi_nunca_se_parte_y_se_ajusta_al_ancho_de_su_tarjeta():
    css = _leer("static", "css", "ux.css")
    valor = _regla(css, ".ux-kpi-valor")
    assert "white-space: nowrap" in valor and "overflow-wrap: anywhere" not in valor            # «anywhere» partía el número en cualquier dígito
    assert re.search(r"font-size:\s*clamp\(1rem,\s*\d+cqw,\s*1\.9em\)", valor)                  # entre 16 px y 1,9 em según el ancho de la tarjeta
    assert "container-type: inline-size" in _regla(css, ".ux-kpi")                               # la tarjeta es el contenedor que mide el número


def test_la_pastilla_de_variacion_nunca_baja_de_12_px():
    css = _leer("static", "css", "ux.css")
    assert "font-size: max(12px, 0.82em)" in _regla(css, ".ux-delta")


# ── Precios: solo es «todo bien» si se analizó todo ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def renderizar():
    import app as modulo_app
    from flask import render_template

    def _render(plantilla, **contexto):
        with modulo_app.app.test_request_context("/"):
            return render_template(plantilla, **contexto)
    return _render


def _item(n):
    return {"id_meli": f"MLA{n}", "titulo": f"Campera {n}", "thumbnail": None, "precio": 10000.0, "minimo": 6000.0, "recomendado": 8000.0, "margen_actual": 35.0, "estado": "ok",
            "comision": 1800.0, "envio": 1500.0, "costo": 3000.0, "unidades": 3, "perdida_mensual": 0.0, "u": 3, "ganancia_unitaria": 3700.0}


def _datos_precios(analizadas, sin_costo, sin_ventas):
    items = [_item(i) for i in range(analizadas)]
    return dict(items=items, pierden=[], justos=[], bien=[],           # (`bien` es solo el detalle plegado: sin filas, la plantilla no pide más datos por publicación)
                 sin_costo=[{"id_meli": f"C{i}", "titulo": f"Sin costo {i}", "thumbnail": None, "precio": 9000.0} for i in range(sin_costo)],
                sin_ventas=[{"id_meli": f"V{i}", "titulo": f"Sin ventas {i}", "thumbnail": None, "precio": 9000.0} for i in range(sin_ventas)],
                total_activas=analizadas + sin_costo + sin_ventas, perdida_mensual=0.0, margen_objetivo=20.0, publicidad_pct=0.0, ventana_dias=90, active_nav="precios")


def test_con_publicaciones_sin_analizar_no_se_celebra_con_un_tilde_verde(renderizar):
    html = renderizar("precios.html", **_datos_precios(analizadas=30, sin_costo=13, sin_ventas=27))
    assert "Las que se pudieron analizar cubren tu margen" in html and "30 de 70" in html
    assert "Faltan <b>40</b> sin calcular" in html
    assert 'class="ux-hero ux-info"' in html and 'class="ux-hero ux-ok"' not in html                 # celeste, no verde
    assert "Todos tus precios cubren el margen que buscás" not in html                                # y sin el cartel de «todo bien» del final


def test_con_todo_analizado_y_bien_si_se_celebra(renderizar):
    html = renderizar("precios.html", **_datos_precios(analizadas=30, sin_costo=0, sin_ventas=0))
    assert "Todos tus precios cubren tu margen" in html and 'class="ux-hero ux-ok"' in html and "sin calcular" not in html.split("ux-hero-nota")[0].split("ux-hero-frase")[-1]


# ── Publicidad: las fechas del período anterior ─────────────────────────────────────────────────────────────────────────────

def test_el_periodo_anterior_de_publicidad_viaja_en_iso_y_se_ve_con_nombre_de_mes(monkeypatch):
    import publicidad
    from utils import rango_fechas
    monkeypatch.setattr(publicidad.ads, "obtener_campanas_con_metricas",
                        lambda token, adv, desde, hasta: [{"costo": 100.0, "ventas_atribuidas": 500.0}])
    r = publicidad._comparar_con_periodo_anterior("tok", "A1", "2026-09-29", "2026-10-12", 80.0, 400.0, 5.0)
    assert (r["desde"], r["hasta"]) == ("2026-09-15", "2026-09-28")                                       # el período anterior de igual largo (14 días)
    assert rango_fechas(r["desde"], r["hasta"]) == "15 – 28 sep"                                          # (con «dd/mm» esto daba «—»)


# ── Un solo nombre para la calculadora ──────────────────────────────────────────────────────────────────────────────────────

def test_la_calculadora_se_llama_igual_en_la_pestana_y_en_el_titulo():
    nav = _leer("nav_config.py")
    assert '"label": "Calculadora"' in nav and "Calculadora MeLi" not in nav
    assert "Calculadora MeLi" not in _leer("templates", "sincronizando.html")


def test_el_ejemplo_de_fechas_usa_el_mes_de_la_fecha_y_no_el_actual():
    from utils import rango_fechas
    assert rango_fechas(date(2026, 9, 15), date(2026, 9, 28)) == "15 – 28 sep"


# ── Costos sin gastos, Día a día y Cuenta ───────────────────────────────────────────────────────────────────────────────────

def test_costos_sin_gastos_no_muestra_tres_tarjetas_en_cero_y_enlaza_a_donde_cargarlos():
    costos = _leer("templates", "costos.html")
    assert "{% set sin_gastos = (stats.fijos_raw == 0 and stats.variables_raw == 0) %}" in costos
    bloque = costos[costos.index('{% if not sin_gastos %}'):costos.index("{% endif %}", costos.index('{% if not sin_gastos %}'))]
    assert bloque.count("kpi(") == 3                                                                # las tres tarjetas de gastos solo salen si hay gastos
    assert 'id="aviso-sin-gastos"' in costos and 'href="#gastos-negocio"' in costos and 'id="gastos-negocio"' in costos


def test_dia_a_dia_muestra_el_resumen_de_hoy_con_numeros_y_no_una_frase_que_explica_lo_obvio():
    dia = _leer("templates", "dia.html")
    assert "todo en una sola pantalla" not in dia and "Despacho, preguntas, pendientes y reputación de hoy." not in dia          # la frase se fue
    assert 'class="dia-resumen"' in dia and 'href="#despacho"' in dia and 'href="#preguntas"' in dia and 'href="#pendientes"' in dia    # y en su lugar, cada número lleva a su parte
    assert "por despachar" in dia and "pendiente{{ '' if misiones|length == 1 else 's' }}" in dia


def test_el_nombre_de_la_cuenta_se_muestra_como_lo_informa_mercado_libre_si_no_hay_nombre_de_negocio():
    """Antes se pasaba por |capitalize / |title y «NOENOEINDUMENTARIA» quedaba «Noenoeindumentaria», que parecía un error de tipeo (D79, 2026-10-22)."""
    cuenta = _leer("templates", "cuenta.html")
    assert "c.nombre_negocio or c.nickname }}" in cuenta and "|capitalize" not in cuenta

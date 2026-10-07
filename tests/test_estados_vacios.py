"""
Una cuenta NUEVA (sin ventas ni publicaciones) no tiene que ver una pared de ceros ni un "todo bien" en verde: ve qué va a pasar y el próximo paso. Se prueba renderizando
las plantillas con datos vacíos (la app real, sin tocar la base).
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402

STATS = {"activas": 0, "valor_total": "0,00", "propio": 0, "full": 0}


def _render(plantilla, **contexto):
    with aplicacion.app.test_request_context("/"):
        return aplicacion.render_template(plantilla, active_nav="x", **contexto)


def test_el_dashboard_de_una_cuenta_sin_ventas_muestra_la_bienvenida_y_esconde_los_ceros():
    html = _render("dashboard_personalizable.html", hay_ventas=False, mono=None, ventas_por_provincia=None, cuando_compran=None, proyeccion=None)
    assert "Todavía no hay ventas para mostrar" in html and 'href="/costos"' in html
    assert '<div id="dashboard-con-datos" hidden>' in html


def test_el_dashboard_de_una_cuenta_con_ventas_se_ve_completo():
    html = _render("dashboard_personalizable.html", hay_ventas=True, mono=None, ventas_por_provincia=None, cuando_compran=None, proyeccion=None)
    assert "Todavía no hay ventas para mostrar" not in html
    assert '<div id="dashboard-con-datos">' in html


def test_stock_sin_catalogo_no_dice_stock_sano():
    html = _render("index.html", productos=[], stats=STATS, full_no_disponible={"total": 0, "items": []}, reactivables=[], riesgo=[], modelos_en_riesgo=set())
    assert "Todavía no hay publicaciones sincronizadas" in html
    assert '<div id="stock-con-datos" hidden>' in html


def test_pendientes_de_una_cuenta_sin_datos_no_felicita():
    contexto = dict(misiones=[], mensaje_todo_bien=True, mensaje_coach=None, coach_pendiente=False, conteo_por_prioridad={"urgente": 0, "importante": 0, "opcional": 0},
                    logros_resueltos=[], recien_resueltas=0)
    sin_datos = _render("logros.html", cuenta_sin_datos=True, **contexto)
    assert "Todavía no hay nada para revisar" in sin_datos and "lo estás haciendo bien" not in sin_datos
    con_datos = _render("logros.html", cuenta_sin_datos=False, **contexto)
    assert "Todo en orden" in con_datos and "lo estás haciendo bien" in con_datos

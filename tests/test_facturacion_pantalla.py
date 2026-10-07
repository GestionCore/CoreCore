"""
Pantalla de Facturación: la factura agrupada por lo que es cada cargo (con Flex marcado aparte), sin el cartel viejo de "cargos que no están en la ganancia" (ahora ya se
descuentan en Ganancia Real) y con el cuadro de lo acreditado y lo que falta, que antes estaba solo en Cobros. Se renderiza la plantilla con datos armados a mano.
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402
import cobros  # noqa: E402
import facturacion as f  # noqa: E402

RESUMEN = {"bill_includes": {
    "charges": [
        {"type": "CVFV", "label": "CVFV", "group_description": "Cargos por venta\t", "amount": 2000.0},
        {"type": "CFF", "label": "Cargo por Mercado Envíos", "group_description": "Cargos por envíos", "amount": 1500.0},
        {"type": "PADS", "label": "Campañas de publicidad - Product Ads", "group_description": "Publicidad", "amount": 1300.0},
        {"type": "CFWA", "label": "Cargo por servicio de almacenamiento Full", "group_description": "Cargos de envíos full", "amount": 25.0},
        {"type": "CESM", "label": "Cargo de mantenimiento de eShop", "group_description": "Cargos de eShop", "amount": 150.0},
    ],
    "bonuses": [{"type": "BFF", "label": "Bonificación cargo por Mercado Envíos", "group_description": "Bonificaciones", "amount": -180.0}],
}}
PERIODOS = [
    {"key": "2026-10-01", "period": {"date_from": "2026-09-09", "date_to": "2026-10-08"}, "period_status": "OPEN", "amount": 5000.0, "unpaid_amount": 1400.0},
    {"key": "2026-09-01", "period": {"date_from": "2026-08-09", "date_to": "2026-09-08"}, "period_status": "CLOSED", "amount": 3600.0, "unpaid_amount": 0.0},
]


def _render(flex_neto=0.0, periodos=PERIODOS):
    agrupada = f.agrupar_factura(RESUMEN, flex_neto, 0.10)
    factura = cobros.resumen_factura(periodos)
    rs = {"facturado": 12000.0, "cargos": agrupada["total_factura"], "flex": flex_neto, "gastos": 0.0, "ganancia_bruta": 7000.0, "ganancia_neta": 7000.0,
          "pendiente": 1400.0, "percepciones": 0.0, "pagos_cobrados": -3700.0, "adeudado": 1400.0}
    vista = [{"key": p["key"], "date_from": p["period"]["date_from"], "date_to": p["period"]["date_to"], "en_curso": p["period_status"] == "OPEN"} for p in periodos]
    with aplicacion.app.test_request_context("/"):
        return aplicacion.render_template(
            "facturacion.html", periodos=vista, key_seleccionada=periodos[0]["key"], filas_factura=agrupada["filas"], factura=factura, total_factura=agrupada["total_factura"],
            total_con_flex=agrupada["total"], flex_neto=flex_neto, rs=rs, waterfall_facturacion=None, active_nav="facturacion")


def test_el_cartel_viejo_ya_no_esta_porque_esos_cargos_se_descuentan_en_ganancia_real():
    html = _render()
    assert "no están en la ganancia de cada venta" not in html and "cargalos como gasto" not in html
    assert "ya están descontados en" in html and 'href="/metricas"' in html


def test_la_tabla_agrupa_por_lo_que_es_cada_cargo_y_el_almacenamiento_no_figura_como_envio():
    html = _render()
    assert "Servicios de FULL (almacenamiento y retiros)" in html and "Cargos de envíos full" not in html
    assert "Cargo por servicio de almacenamiento Full" not in html or html.index("Servicios de FULL") < html.index("Cargo por servicio de almacenamiento Full")
    assert 'class="data-table tabla-factura"' in html


def test_con_flex_el_envio_lo_suma_marcado_como_no_facturado_por_mercado_libre():
    sin = _render(0.0)
    con = _render(900.0)
    assert "Envíos Flex" not in sin
    assert "Envíos Flex (tu propia logística)" in con and "no figura en la factura de Mercado Libre" in con
    assert "Reintegro de Mercado Libre por envíos Flex (10%)" in con
    assert "más lo que te cuestan tus envíos Flex" in con


def test_el_cuadro_de_lo_acreditado_y_lo_que_falta_tambien_esta_en_facturacion_con_su_rango_de_fechas():
    html = _render()
    assert "Lo acreditado y lo que falta de esta factura" in html
    assert "Ya descontado" in html and "Falta" in html
    assert "9 sep – 8 oct" in html                              # antes salía «—»: el formateador de fechas recibía 09/09/2026 en lugar de la fecha ISO


def test_el_cuadro_sigue_en_cobros_con_el_rango_de_fechas_y_el_link_al_detalle():
    with aplicacion.app.test_request_context("/"):
        html = aplicacion.render_template("_factura_estado.html", factura=cobros.resumen_factura(PERIODOS), detalle_en_facturacion=True)
    assert "9 sep – 8 oct" in html and 'href="/facturacion"' in html

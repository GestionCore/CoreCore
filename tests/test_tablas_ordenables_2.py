"""
Más tablas que se ordenan por columna (static/js/tablas.js): campañas de Publicidad, historial de precios y ventas manuales. Las fechas se ven como «2 sep» (nunca «2026-09-02») y el orden
real sale del ISO guardado en data-orden. Se renderizan las plantillas con filas de ejemplo (las cuentas de prueba no tienen cambios de precio ni ventas manuales).
"""
import re

import pytest


@pytest.fixture
def renderizar():
    import app as modulo_app
    from flask import render_template

    def _render(plantilla, **contexto):
        with modulo_app.app.test_request_context("/"):
            return render_template(plantilla, **contexto)
    return _render


def _tabla(html):
    return re.search(r"<table class=\"data-table\" data-ordenable>.*?</table>", html, re.S).group(0)


def test_el_historial_de_precios_se_ordena_y_muestra_la_fecha_legible(renderizar):
    cambios = [
        {"id_meli": "MLA1", "titulo": "Zapatilla Azul", "thumbnail": None, "precio_anterior": 1000, "precio_nuevo": 1200, "direccion": "subió", "fecha_cambio": "2026-09-02",
         "unidades_antes": 4, "unidades_despues": 6, "variacion_pct": 50.0, "datos_incompletos": False},
        {"id_meli": "MLA2", "titulo": "Buzo Gris", "thumbnail": None, "precio_anterior": 3000, "precio_nuevo": 2500, "direccion": "bajó", "fecha_cambio": "2025-12-30",
         "unidades_antes": 0, "unidades_despues": 2, "variacion_pct": None, "datos_incompletos": True},
    ]
    tabla = _tabla(renderizar("historial_precios.html", cambios=cambios, active_nav="historial_precios"))
    assert len(re.findall(r"<th[^>]*data-orden=", tabla)) == 6
    assert "2026-09-02</td>" not in tabla and "2025-12-30</td>" not in tabla                  # nunca la fecha en ISO a la vista
    assert ">2 sep<" in tabla and ">30 dic 2025<" in tabla and 'data-orden="2026-09-02"' in tabla          # legible, y el orden sale del ISO
    assert 'data-orden="zapatilla azul"' in tabla and 'data-orden="1200"' in tabla and 'data-orden="50.0"' in tabla
    assert 'data-orden=""' in tabla                                                                # un cambio sin variación (sin ventas previas) va siempre al final al ordenar


def test_las_ventas_manuales_se_ordenan_y_muestran_la_fecha_legible(renderizar):
    ventas = [{"id": 1, "id_orden": "m1", "titulo": "Termo 1L", "id_variante": "v1", "cantidad": 2, "precio_venta": 18000, "precio_formateado": "18.000", "total": 36000, "fecha": "2026-10-01",
               "comprador_nombre": "Ana", "thumbnail": None}]
    tabla = _tabla(renderizar("ventas_manuales.html", catalogo=[], ventas=ventas, hoy="2026-10-08", active_nav="ventas_manuales", aviso=""))
    assert len(re.findall(r"<th[^>]*data-orden=", tabla)) == 5                                       # la última columna (borrar) no se ordena
    assert "2026-10-01</td>" not in tabla and ">1 oct<" in tabla and 'data-orden="2026-10-01"' in tabla
    assert 'data-orden="termo 1l"' in tabla


def test_las_campanas_de_publicidad_se_ordenan_por_cada_columna():
    html = open("templates/publicidad.html", encoding="utf-8").read()
    tabla = re.search(r"<table class=\"data-table\" data-ordenable>.*?</thead>", html, re.S).group(0)
    assert len(re.findall(r"<th[^>]*data-orden=", tabla)) == 10
    assert re.search(r'data-orden="num" data-primero="asc"[^>]*>ACOS', tabla)                         # en el ACOS «mejor» es el más bajo: primero los más bajos

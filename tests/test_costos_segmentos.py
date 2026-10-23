"""
Ola 3 (D24, D33, D34): Costos tiene UNA herramienta por pestaña —Costo de fabricación · Gastos · Entrega Flex · Importar desde Excel—, cada una con su único botón principal; la planilla de Excel
tiene su atajo junto al título y la ayuda larga va plegada. Antes eran cuatro herramientas apiladas en 5.700 px de celular con cuatro botones violetas.
(D56, «guardar al salir del campo», se revisó y se dejó como está: con los costos agrupados en modelos hay un «Aplicar» por modelo y una sola barra «Guardar costos» que muestra el antes
y el después antes de pisar uno ya cargado; autoguardar cada campo sacaría esa confirmación sobre plata.)
"""
import os
import re

import pytest

from tests.test_costos_modelos import _contexto, _pub

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fuente():
    return open(os.path.join(RAIZ, "templates", "costos.html"), encoding="utf-8").read().replace("\r\n", "\n")


def _paneles(fuente):
    """{id del panel: su HTML sin los <script>}: lo que ve la persona dentro de cada pestaña."""
    sin_scripts = re.sub(r"<script.*?</script>", "", fuente, flags=re.S)
    return {m.group(1): m.group(0) for m in re.finditer(r'<section class="ux-tab-panel" id="([a-z-]+)".*?\n</section>', sin_scripts, re.S)}


def test_las_pestanas_van_en_este_orden_y_cada_una_con_su_titulo():
    f = _fuente()
    assert f.count('<div class="ux-tabs" data-tabs id="segmentos-costos">') == 1
    ids = re.findall(r'<section class="ux-tab-panel" id="([a-z-]+)" data-tab-titulo="([^"]+)"', f)
    assert ids == [("costos-fabricacion", "Costo de fabricación"), ("gastos-negocio", "Gastos"), ("entrega-flex", "Entrega Flex"), ("importar-costos", "Importar desde Excel")]


def test_cada_pestana_tiene_a_lo_sumo_un_boton_principal_y_el_del_chat_de_gastos_no_lo_es():
    paneles = _paneles(_fuente())
    assert set(paneles) == {"costos-fabricacion", "gastos-negocio", "entrega-flex", "importar-costos"}
    for id_panel, html in paneles.items():
        assert len(re.findall(r'class="btn btn-primary[ "]', html)) <= 1, id_panel
    assert 'class="btn btn-primary">Agregar gasto' in paneles["gastos-negocio"] and 'class="btn btn-secondary">Enviar' in paneles["gastos-negocio"]
    assert "Subir la planilla completa" in paneles["importar-costos"] and "Guardar y ver qué envíos resuelve" in paneles["entrega-flex"]


def test_solo_flex_es_condicional_y_el_excel_se_ve_en_cualquier_cuenta_con_su_atajo_arriba():
    f = _fuente()
    assert f.index('href="#importar-costos"') < f.index('<div class="ux-tabs" data-tabs id="segmentos-costos">')          # el atajo junto al título
    inicio = f.index("{% if capacidades.get('flex') is not false %}")
    fin = f.index("{% endif %}", f.index('id="entrega-flex"'))
    assert inicio < f.index('id="entrega-flex"') < fin < f.index('id="importar-costos" data-tab-titulo')
    assert f.count("capacidades.get('flex') is not false") == 2                           # el panel de Flex y el aviso de envíos devueltos dentro de Gastos; el Excel no depende de ninguno


def test_la_barra_de_cambios_sin_guardar_queda_fuera_de_las_pestanas():
    """Si estuviera adentro de una pestaña, al pasar a otra desaparecería con costos todavía sin guardar."""
    f = _fuente()
    fin_pestanas = f.index("</div>\n\n{% if productos %}\n<div class=\"ux-barra-accion\" id=\"barra-costos\"")
    assert f.index('<div class="ux-tabs" data-tabs id="segmentos-costos">') < f.index('id="importar-costos" data-tab-titulo') < fin_pestanas
    assert f.count('id="barra-costos"') == 1


def test_la_ayuda_larga_va_plegada():
    f = _fuente()
    ayuda = f[f.index('<details class="ux-detalle" id="ayuda-costos">'):]
    ayuda = ayuda[:ayuda.index("</details>")]
    assert "¿Cómo se cargan los costos?" in ayuda and "tocá <b>Aplicar</b>" in ayuda and "Guardar costos" in ayuda
    assert "open" not in f[f.index('<details class="ux-detalle" id="ayuda-costos">'):][:60]                # cerrada de entrada


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")
def test_la_pantalla_renderiza_las_cuatro_pestanas_y_los_enlaces_de_otras_pantallas_caen_en_una():
    import app as modulo
    from flask import render_template
    productos = [_pub("sola", "Gorra Lisa Roja", None, costo=3000.0)]
    contexto = {**_contexto(productos), "capacidades": {}}
    with modulo.app.test_request_context("/costos"):
        html = render_template("costos.html", **contexto)
    for ancla in ("costos-fabricacion", "gastos-negocio", "entrega-flex", "importar-costos"):
        assert f'id="{ancla}"' in html
    assert 'action="/costos#gastos-negocio"' in html                                    # elegir un período en Gastos vuelve a la pestaña de Gastos
    # y una cuenta sin Flex no tiene su pestaña ni el aviso de envíos devueltos, pero sí el Excel
    with modulo.app.test_request_context("/costos"):
        sin_flex = render_template("costos.html", **{**contexto, "capacidades": {"flex": False}})
    assert 'id="entrega-flex"' not in sin_flex and 'id="importar-costos"' in sin_flex


def test_agregar_o_eliminar_un_gasto_vuelve_a_la_pestana_de_gastos():
    app_py = open(os.path.join(RAIZ, "app.py"), encoding="utf-8").read()
    assert app_py.count('#gastos-negocio") if periodo else redirect("/costos#gastos-negocio")') == 1
    assert '{deshacer}#gastos-negocio")' in app_py


def test_una_recarga_vuelve_a_la_pestana_en_la_que_se_estaba_pero_entrar_desde_afuera_no():
    f = _fuente()
    assert "nav.type === 'reload'" in f and "corelux_costos_pestana" in f and "if (!recarga || location.hash || !previa) return;" in f
    assert "try { previa = sessionStorage.getItem(CLAVE); }" in f                          # el almacenamiento puede no estar: nunca rompe la pantalla

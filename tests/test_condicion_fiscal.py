"""
Condición fiscal por cuenta: nunca se supone. No todos los vendedores son monotributistas (hay responsables inscriptos y quien todavía no está inscripto), así que Monotributo
solo se muestra a quien lo declaró y a quien no contó nada se le pregunta. Sin tocar la base (los datos reales no se modifican en las pruebas).
"""
import os

import pytest

import fiscal
import monotributo
import nav_config
import onboarding


def test_las_condiciones_conocidas_son_tres_y_nada_mas_es_valido():
    assert set(fiscal.CONDICIONES) == {"monotributo", "responsable_inscripto", "sin_inscripcion"}
    assert fiscal.es_valida("monotributo") and not fiscal.es_valida("") and not fiscal.es_valida(None) and not fiscal.es_valida("inventada")
    assert fiscal.etiqueta(None) == "Sin informar" and fiscal.etiqueta("responsable_inscripto") == "Responsable inscripto"


def test_solo_se_esconde_monotributo_si_se_sabe_que_no_corresponde():
    assert fiscal.capacidad_monotributo(None) is None                 # sin informar: no se esconde nada ni se supone nada
    assert fiscal.capacidad_monotributo("inventada") is None
    assert fiscal.capacidad_monotributo("monotributo") is True
    assert fiscal.capacidad_monotributo("responsable_inscripto") is False
    assert fiscal.capacidad_monotributo("sin_inscripcion") is False


def test_un_valor_invalido_se_rechaza_antes_de_tocar_la_base():
    assert fiscal.guardar(1, 1, "monotributista_de_la_luna") is False


def test_el_onboarding_ofrece_las_tres_condiciones_y_la_opcion_de_decirlo_despues():
    assert set(onboarding.OPCIONES_FISCAL) == set(fiscal.CONDICIONES) | {""}
    assert onboarding.OPCIONES_FISCAL[""] == "Prefiero decirlo después"


def test_el_onboarding_rechaza_una_condicion_inexistente_sin_guardar_nada():
    assert onboarding.guardar_respuestas(1, ["todo"], "nuevo", "dashboard", condicion_fiscal="otra") is False


def test_el_checklist_pide_la_condicion_fiscal_solo_si_se_la_pregunta():
    sin_preguntar = onboarding.armar_checklist(True, True, 10, 10, True, True)
    assert "fiscal" not in [p["id"] for p in sin_preguntar["pasos"]]
    sin_contar = onboarding.armar_checklist(True, True, 10, 10, True, True, condicion_fiscal=None)
    paso = next(p for p in sin_contar["pasos"] if p["id"] == "fiscal")
    assert paso["completo"] is False and paso["link"] == "/cuenta#condicion-fiscal"
    contada = onboarding.armar_checklist(True, True, 10, 10, True, True, condicion_fiscal="responsable_inscripto")
    assert next(p for p in contada["pasos"] if p["id"] == "fiscal")["completo"] is True


def test_el_menu_trae_monotributo_condicionado_a_la_capacidad():
    pagina = next(p for p in nav_config.GRUPOS_NAV["ventas"]["paginas"] if p["nav_key"] == "monotributo")
    assert pagina["requiere"] == "monotributo"


def test_la_busqueda_de_atajos_tampoco_ofrece_monotributo_a_quien_se_sabe_que_no_lo_es():
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js", "global.js"), encoding="utf-8").read()
    assert "texto: 'Ir a Monotributo', url: '/monotributo', requiere: 'monotributo'" in js


# ── Las pantallas ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
pytestmark_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")

ANALISIS = dict(facturacion_12m=9_000_000.0, categoria_real="A", categoria_declarada=None, cuota_mensual_declarada=None, tope_categoria_declarada=None,
                variacion_pct_propia=None, meses_para_cruzar=None, alertas=[], escalas=monotributo.ESCALAS, vigente_desde=monotributo.ESCALAS_VIGENTES_DESDE)


def _render_monotributo(condicion, capacidades=None):
    import app as aplicacion
    contexto = dict(ANALISIS) if condicion == "monotributo" else {}
    with aplicacion.app.test_request_context("/"):
        return aplicacion.render_template("monotributo.html", condicion=condicion, condiciones_fiscales=fiscal.CONDICIONES, detalles_condicion=fiscal.DETALLES,
                                          active_nav="monotributo", capacidades=capacidades or {}, **contexto)


@pytestmark_db
def test_sin_declarar_se_pregunta_y_no_se_muestra_ningun_calculo():
    html = _render_monotributo(None)
    assert "Contanos tu condición fiscal" in html and 'action="/cuenta/condicion_fiscal"' in html
    assert "Tabla de escalas vigente" not in html and "Techo usado" not in html
    assert 'name="condicion" value="monotributo"  checked' not in html and html.count("checked") == 1       # nada marcado de antemano, salvo «Todavía no lo sé»
    assert 'value="" checked' in html


@pytestmark_db
def test_un_responsable_inscripto_ve_una_explicacion_y_no_las_escalas():
    html = _render_monotributo("responsable_inscripto")
    assert "Esta pantalla es para monotributistas" in html and "Responsable inscripto" in html
    assert "Tabla de escalas vigente" not in html
    assert 'value="responsable_inscripto" checked' in html


@pytestmark_db
def test_un_monotributista_ve_el_analisis_completo():
    html = _render_monotributo("monotributo")
    assert "Tabla de escalas vigente" in html and "Contanos tu condición fiscal" not in html


@pytestmark_db
def test_el_menu_esconde_monotributo_solo_si_la_capacidad_es_falsa():
    escondida = _render_monotributo("responsable_inscripto", capacidades={"monotributo": False})
    visible = _render_monotributo(None, capacidades={})
    assert 'href="/monotributo" class="subnav-tab' not in escondida
    assert 'href="/monotributo" class="subnav-tab' in visible


@pytestmark_db
def test_mi_cuenta_trae_el_formulario_de_la_condicion_fiscal():
    import app as aplicacion
    with aplicacion.app.test_request_context("/"):
        html = aplicacion.render_template("cuenta.html", active_nav="cuenta", plan="trial", nombre_plan="Prueba", email=None, dias_trial=None, pagos_habilitados=False, contacto="x@y.z",
                                          condicion_fiscal_actual="monotributo", condiciones_fiscales=fiscal.CONDICIONES, detalles_condicion=fiscal.DETALLES)
    assert 'id="condicion-fiscal"' in html and 'value="monotributo" checked' in html and 'name="volver" value="/cuenta"' in html
    assert "No la suponemos" in html


@pytestmark_db
def test_el_onboarding_trae_la_cuarta_pregunta():
    import app as aplicacion
    with aplicacion.app.test_request_context("/"):
        html = aplicacion.render_template("onboarding.html", opciones_prioridad=onboarding.OPCIONES_PRIORIDAD, opciones_experiencia=onboarding.OPCIONES_EXPERIENCIA,
                                          opciones_pantalla=onboarding.OPCIONES_PANTALLA, opciones_fiscal=onboarding.OPCIONES_FISCAL)
    assert 'data-paso="4"' in html and "¿Cuál es tu condición fiscal?" in html and 'name="condicion_fiscal"' in html
    assert html.count('name="condicion_fiscal"') == 4 and "Prefiero decirlo después" in html

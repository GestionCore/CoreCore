"""
«Día a día» en una sola pantalla: despacho, preguntas, pendientes y reputación una debajo de la otra; las pestañas saltan a cada parte. Las pantallas sueltas de antes
(/despacho, /preguntas, /logros, /reputacion) redirigen a su parte.
"""
import os
import re

import pytest

import nav_config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")
PAGINAS = nav_config.GRUPOS_NAV["dia"]["paginas"]


def test_las_cuatro_pestañas_van_a_una_sola_pantalla_con_su_ancla():
    assert {p["href"] for p in PAGINAS} == {"/dia"} and {p["endpoint"] for p in PAGINAS} == {"dia_vista"}
    assert [p["ancla"] for p in PAGINAS] == ["despacho", "preguntas", "pendientes", "reputacion"]
    assert len({p["ancla"] for p in PAGINAS}) == 4


def test_no_se_destaca_una_pantalla_mas_usada_donde_todo_es_la_misma_pagina():
    assert nav_config.GRUPOS_NAV["dia"]["una_pantalla"] is True
    assert nav_config.calcular_mas_usado({"despacho": 50, "preguntas": 1, "logros": 0, "reputacion": 0}) == {}
    assert nav_config.calcular_mas_usado({"stock": 5, "stock_masivo": 1, "despacho": 50, "preguntas": 1}) == {"stock": "stock"}      # el resto sigue funcionando


def test_cada_pestaña_tiene_su_seccion_en_la_pagina():
    html = open(os.path.join(RAIZ, "templates", "dia.html"), encoding="utf-8").read()
    for p in PAGINAS:
        assert f'<section class="dia-seccion" id="{p["ancla"]}"' in html, p["ancla"]
    assert html.index('id="despacho"') < html.index('id="preguntas"') < html.index('id="pendientes"') < html.index('id="reputacion"')


def test_el_menu_arma_el_link_de_cada_pestaña_con_su_ancla():
    base = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    assert '{{ item.href }}{% if item.ancla %}#{{ item.ancla }}{% endif %}' in base


def test_las_pantallas_sueltas_dejaron_de_ser_plantillas_y_viven_como_secciones():
    for viejo in ("despacho", "preguntas", "logros", "reputacion"):
        assert not os.path.exists(os.path.join(RAIZ, "templates", viejo + ".html")), viejo
    for nuevo in ("despacho", "preguntas", "pendientes", "reputacion"):
        assert os.path.exists(os.path.join(RAIZ, "templates", f"_dia_{nuevo}.html")), nuevo


def test_cada_seccion_tiene_un_titulo_de_segundo_nivel_y_solo_la_pagina_tiene_el_de_primero():
    for nombre in ("despacho", "preguntas", "pendientes", "reputacion"):
        t = open(os.path.join(RAIZ, "templates", f"_dia_{nombre}.html"), encoding="utf-8").read()
        assert "<h1" not in t and t.count('<h2 class="page-title">') == 1, nombre


def test_los_links_de_otras_pantallas_ya_apuntan_a_la_seccion_correcta():
    js = open(os.path.join(RAIZ, "static", "js", "global.js"), encoding="utf-8").read()
    for ancla, texto in (("despacho", "Despacho"), ("reputacion", "Reputación"), ("pendientes", "Pendientes")):
        assert f"texto: 'Ir a {texto}', url: '/dia#{ancla}'" in js
    import dashboard
    avisos = dashboard.armar_avisos(2, 0, 0, 0)
    assert avisos["items"][0]["href"] == "/dia#preguntas"


def test_el_css_deja_lugar_para_la_barra_y_respeta_a_quien_prefiere_menos_movimiento():
    css = open(os.path.join(RAIZ, "static", "css", "ux.css"), encoding="utf-8").read()
    assert re.search(r"\.dia-seccion\s*\{[^}]*scroll-margin-top", css)
    assert "html:has(.dia-seccion) { scroll-behavior: smooth; }" in css
    assert re.search(r"prefers-reduced-motion: reduce\)\s*\{\s*html:has\(\.dia-seccion\)\s*\{\s*scroll-behavior: auto", css)


# ── La pantalla ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
CONTEXTO = dict(
    paquetes=[], fecha="2026-10-07", total=0, listos=0, cantidad_shipments=0, corte_correo={"hora": "13:00", "estado": "informado"}, corte_flex=None, cortes_js=[{"nombre": "Correo", "hora": "13:00"}], flex_habilitado=False, umbrales_flex=[],
    misiones=[], mensaje_todo_bien=True, cuenta_sin_datos=False, mensaje_coach=None, coach_pendiente=False, conteo_por_prioridad={"urgente": 0, "importante": 0, "opcional": 0},
    logros_resueltos=[], recien_resueltas=0, rep=None, incidencias_por_tipo={"devoluciones": 0, "reclamos": 0, "reclamos_sin_impacto": 0, "cancelaciones": 0},
)


def _render(errores=None):
    import app as aplicacion
    with aplicacion.app.test_request_context("/dia"):
        return aplicacion.render_template("dia.html", active_nav="despacho", errores=errores or {}, **CONTEXTO)


@CON_BASE
def test_la_pantalla_trae_las_cuatro_partes_con_su_encabezado_y_un_solo_titulo_principal():
    html = _render()
    assert html.count("<h1") == 1 and "Día a día" in html
    for ancla, titulo in (("despacho", "Despacho"), ("preguntas", "Preguntas"), ("pendientes", "Pendientes"), ("reputacion", "Reputación")):
        seccion = html.split(f'id="{ancla}"')[1].split("</section>")[0]
        assert f">{titulo}</h2>" in seccion, ancla


@CON_BASE
def test_las_pestañas_de_la_seccion_apuntan_a_las_anclas():
    html = _render()
    for ancla in ("despacho", "preguntas", "pendientes", "reputacion"):
        assert f'href="/dia#{ancla}"' in html
    # y el script que marca la pestaña de lo que se está mirando
    assert "la parte actual es la última cuyo borde de arriba ya pasó" in html


@CON_BASE
def test_no_hay_ids_repetidos_entre_las_cuatro_partes():
    html = _render()
    ids = re.findall(r'\sid="([^"]+)"', html)
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    assert not repetidos, repetidos


@CON_BASE
def test_si_una_parte_falla_las_demas_se_muestran_y_la_que_fallo_avisa():
    html = _render(errores={"despacho": True, "pendientes": True, "reputacion": True})
    assert html.count("No pudimos armar esta parte") == 3
    assert 'id="preguntas"' in html and "Respondé desde acá" in html                                # Preguntas no depende de nada que pudiera fallar
    sana = _render()
    assert "No pudimos armar esta parte" not in sana


@CON_BASE
def test_los_scripts_de_las_cuatro_partes_no_se_pisan_entre_si(tmp_path):
    """Las cuatro partes comparten una sola página: un `const` o `let` global repetido en dos de ellas rompería el script entero ("ya fue declarado")."""
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node no está instalado")
    html = _render()
    cuerpo = html[html.index("<main"):html.index("</main>")]
    scripts = re.findall(r"<script>(.*?)</script>", cuerpo, flags=re.S)
    assert len(scripts) >= 3
    archivo = tmp_path / "dia.js"
    archivo.write_text("\n;\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(archivo)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:600]

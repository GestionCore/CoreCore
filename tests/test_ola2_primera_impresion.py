"""
Ola 2 del plan de la beta (2026-10-22): primera impresión. Lo que ve alguien que nunca vio CoreLux:

  · la imagen al compartir el link (Facebook, WhatsApp…) y las etiquetas que la usan;
  · una página de Ayuda con qué es cada cosa y las preguntas frecuentes (pública y dentro de la app);
  · Planes con una tabla fila por fila, con los mismos números que los límites reales;
  · el nombre de la cuenta tal como lo informa Mercado Libre, y «Eliminar mi cuenta» lejos de «Cerrar sesión»;
  · el recorrido guiado que termina en la primera tarea real (cargar el costo del producto más vendido) y la lista «Completá tu perfil» con lo que falta primero;
  · «¿Te sirvió esta pantalla?» al pie de cada pantalla.
"""
import os
import re

import pytest

import asistente

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


@pytest.fixture
def cliente(monkeypatch):
    import app as aplicacion
    monkeypatch.setattr(aplicacion.config, "BETA_SOLO_INVITADOS", True)
    return aplicacion.app.test_client()


# ── Imagen para compartir ─────────────────────────────────────────────────────────
def test_la_imagen_para_compartir_mide_1200_por_630_y_pesa_poco():
    from PIL import Image
    ruta = os.path.join(RAIZ, "static", "icons", "og-corelux.png")
    assert os.path.getsize(ruta) < 400_000                                   # WhatsApp y Facebook la descartan si es muy pesada
    with Image.open(ruta) as imagen:
        assert imagen.size == (1200, 630)
    assert os.path.exists(os.path.join(RAIZ, "generar_og.py"))              # cómo se hizo: se puede volver a generar si cambia la marca


def test_la_landing_y_las_paginas_publicas_comparten_con_la_imagen_grande(cliente):
    for ruta in ("/", "/planes", "/beta", "/ayuda", "/terminos"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert "og-corelux.png" in html, ruta
        assert 'content="summary_large_image"' in html and 'property="og:image:width" content="1200"' in html, ruta
        assert 'property="og:title"' in html and 'property="og:description"' in html, ruta
    assert 'content="summary"' not in cliente.get("/").get_data(as_text=True)    # antes: la tarjeta chica con el ícono cuadrado


# ── Ayuda ────────────────────────────────────────────────────────────────────────
def test_la_ayuda_es_publica_y_explica_los_terminos_que_nadie_conoce(cliente):
    r = cliente.get("/ayuda")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "pb-nav" in html and 'class="sidebar"' not in html     # sin sesión: página pública, sin la carcasa de la app
    for termino in ("Ganancia neta real", "FULL", "Flex", "ROAS", "ACOS", "TACOS", "Retenciones", "Cargos de Mercado Libre", "Variante", "Radar"):
        assert f"<dt>{termino}</dt>" in html, termino
    for pregunta in ("¿Por qué mi ganancia parece más alta de lo real?", "aplicación no certificada", "Responsable Inscripto", "¿Cómo descargo o borro mis datos?", "soporte@corelux.app"):
        assert pregunta in html, pregunta


def test_la_ayuda_esta_en_el_menu_el_pie_publico_y_el_mapa_del_sitio(cliente):
    assert "/ayuda" in _leer("templates", "base.html") and "Ayuda y preguntas frecuentes" in _leer("templates", "base.html")
    assert 'href="/ayuda"' in _leer("templates", "_publico.html")
    assert "/ayuda" in cliente.get("/sitemap.xml").get_data(as_text=True)


# ── Planes ────────────────────────────────────────────────────────────────────
def test_la_tabla_de_planes_dice_lo_mismo_que_los_limites_reales(cliente):
    html = cliente.get("/planes").get_data(as_text=True)
    assert 'class="planes-tabla"' in html and "Comparar los dos planes" in html
    base, elite = asistente.limite_diario("base"), asistente.limite_diario("elite")
    assert re.search(rf"Asistente de IA \(consultas por día\)</th><td>{base}</td><td class=\"planes-col-elite\">{elite}</td>", html)
    import config
    assert f"Hasta {config.MAX_CUENTAS_ELITE}" in html
    assert elite > base                                                      # Elite incluye más consultas (lo que prometen la tabla y las tarjetas)


# ── Nombre de la cuenta y menú ───────────────────────────────────────────────────
def test_el_nombre_de_la_cuenta_no_se_pasa_por_title():
    """`|title` convertía «NOENOEINDUMENTARIA» en «Noenoeindumentaria»: parecía un error de tipeo. Se muestra como lo informa Mercado Libre, una sola vez."""
    base = _leer("templates", "base.html")
    assert "_nombre_cuenta|title" not in base and "|title" not in base
    cuenta = _leer("templates", "cuenta.html")
    assert "nickname|capitalize" not in cuenta
    assert "Usuario de Mercado Libre: {{ c.nickname }}" in cuenta            # el apodo solo se repite abajo si hay un nombre de negocio distinto


def test_eliminar_la_cuenta_ya_no_esta_pegado_a_cerrar_sesion():
    assert "/cuenta/eliminar" not in _leer("templates", "base.html")
    assert 'href="/cuenta/eliminar">Eliminar mi cuenta' in _leer("templates", "cuenta.html")      # vive al final de Mi cuenta, con su pantalla de confirmación


# ── Recorrido guiado y lista de perfil ───────────────────────────────────────────
def test_el_recorrido_guiado_termina_en_la_primera_tarea_real():
    js = _leer("static", "js", "global.js")
    bloque = js[js.index("const PASOS_TUTORIAL = ["):js.index("let _tourPasoActual")]
    ultimo = bloque.strip().splitlines()[-2]
    assert "Tu primer paso" in ultimo and "url: '/costos'" in ultimo and "alternativo: '.bottombar'" in ultimo      # en el celular el menú está escondido: se señala la barra de abajo
    assert "function _siguientePaso()" in js and "if (actual && actual.accion)" in js
    saltar = js[js.index("if (!visible(objetivo))"):][:80]
    assert "_siguientePaso()" in saltar                                      # un paso escondido se salta SIN ejecutar su acción (no te manda a Costos sin avisar)


def test_la_lista_de_perfil_muestra_primero_lo_que_falta():
    tpl = _leer("templates", "dashboard_personalizable.html")
    assert "sort((a, b) => Number(a.completo) - Number(b.completo))" in tpl
    assert "i === 0 && !p.completo ? ' primero'" in tpl
    assert ".checklist-item.primero" in _leer("static", "css", "ux.css")


# ── «¿Te sirvió?» ───────────────────────────────────────────────────────────────
def test_cada_pantalla_pregunta_si_te_sirvio_sin_repetirse():
    base = _leer("templates", "base.html")
    assert 'id="te-sirvio"' in base and "¿Te sirvió esta pantalla?" in base
    assert "active_nav not in ('ayuda', 'admin', 'cuenta', 'suscripcion', 'referidos')" in base          # no en las pantallas de la cuenta ni de administración
    assert "DIAS_SIRVIO = 14" in base and "localStorage.getItem(CLAVE_SIRVIO)" in base
    assert "tipo: 'valoracion'" in base                                      # el «Sí» llega a /admin/feedback con su pantalla
    assert "Se puede mejorar" in base and "elegirTipoComentario(document.querySelector('.fb-tipo[data-tipo=\"idea\"]'))" in base


def test_la_clase_para_lectores_de_pantalla_existe():
    assert ".sr-only {" in _leer("static", "css", "style.css")

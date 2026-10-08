"""
Fases 5 y 6 de la auditoría (interfaz, JS y CSP): pestañas de «Más detalle», despachador de eventos ampliado, jerarquía de botones, contraste, capas y animaciones.
"""
import os
import re
import shutil

import pytest

from tests.test_correcciones_frontend import _correr_ux

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── 32. «Más detalle» en pestañas ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_mas_detalle_de_ganancia_real_son_pestañas_y_ya_no_acordeones_apilados():
    t = _leer("templates", "metricas.html")
    assert "<details" not in t and "</details>" not in t
    assert '<div class="ux-tabs" data-tabs id="mas-detalle">' in t and t.count('class="ux-tab-panel"') == 6
    for id_panel in ("seccion-cuotas", "seccion-reclamos", "seccion-factura", "seccion-clientes", "seccion-historial", "det-mercado"):
        assert f'id="{id_panel}"' in t, id_panel
    assert "data-tab-defecto" in t and "reclamos_total > 0" in t                                           # con reclamos abiertos arranca en esa pestaña
    assert t.count("data-tab-titulo=") == 6 and t.count('<h3 class="ux-tab-titulo">') == 6
    assert "#seccion-reclamos" in t                                                                        # los avisos siguen enlazando a la pestaña por su id


def test_los_graficos_se_arman_cuando_su_pestaña_se_muestra():
    t = _leer("templates", "metricas.html")
    assert "addEventListener('ux:tab-visible'" in t and "details[data-grafico]" not in t and "panel.dataset.listo = '1'" in t


def test_el_componente_de_pestañas_tiene_roles_teclado_hash_y_aviso_de_visibilidad():
    js = _leer("static", "js", "ux.js")
    for pieza in ("role', 'tablist'", "setAttribute('role', 'tab')", "aria-selected", "aria-controls", "ArrowRight", "ArrowLeft", "Home", "End", "hashchange", "ux:tab-visible", "data-tab-defecto"):
        assert pieza in js, pieza
    css = _leer("static", "css", "ux.css")
    assert ".ux-tab-panel[hidden] { display: none; }" in css and ".ux-tab-panel[hidden] { display: block !important; }" in css      # y al imprimir salen todos
    assert ".ux-tab-panel[data-grafico]:not([data-listo]) { display: none !important; }" in css and "@media print" in css


def test_la_barra_de_pestañas_y_el_menu_de_secciones_avisan_que_se_deslizan():
    js, css = _leer("static", "js", "ux.js"), _leer("static", "css", "ux.css")
    assert "UX.bordesDeslizables = " in js and "querySelectorAll('.subnav-tabs-inner').forEach(UX.bordesDeslizables)" in js and "UX.bordesDeslizables(barra)" in js
    assert '[data-sombra~="der"]' in css and '[data-sombra~="izq"]' in css and "mask-image" in css


# ── 38. Despachador: fondo de un modal, enlaces que no navegan y teclas ────────────────────────────────────────────────────────────────────
@CON_NODE
def test_el_clic_en_el_fondo_de_un_modal_solo_cierra_si_fue_en_el_fondo(tmp_path):
    r = _correr_ux("""
      caja.cerrar = () => llamadas.push('cerrar');
      const fondo = elemento({ 'data-click': 'cerrar', 'data-click-propio': '' });
      const dentro = elemento({}, fondo);
      disparar('click', dentro);          // un clic en el cuadro de adentro NO cierra
      disparar('click', fondo);           // un clic en el fondo sí
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == ["cerrar"]


@CON_NODE
def test_data_prevenir_cancela_la_navegacion_y_data_keydown_respeta_la_tecla(tmp_path):
    r = _correr_ux("""
      caja.abrir = () => llamadas.push('abrir'); caja.enviar = () => llamadas.push('enviar');
      disparar('click', elemento({ 'data-click': 'abrir', 'data-prevenir': '' }));
      const campo = elemento({ 'data-keydown': 'enviar', 'data-keydown-tecla': 'Enter' });
      disparar('keydown', campo, 'a');
      disparar('keydown', campo, 'Enter');
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == ["preventDefault", "abrir", "enviar"]


def test_base_html_ya_no_tiene_manejadores_inline_y_las_funciones_nuevas_existen():
    base = _leer("templates", "base.html")
    assert not re.search(r'\son(?:click|change|input|keyup|keydown|submit)="', base)
    assert 'data-keydown="enviarMensajeIA" data-keydown-tecla="Enter"' in base and 'data-click="abrirComentario" data-prevenir' in base
    js = _leer("static", "js", "global.js")
    assert "function alternarTemaLateral()" in js and "function contarCaracteresDescripcion(" in js and "window.RangoFechas = RangoFechas;" in js
    assert not re.search(r'on(?:click|input|change|keyup|keydown)="', js)


def test_el_titulo_de_una_sugerencia_viaja_escapado_en_un_atributo_y_no_dentro_de_un_manejador():
    js = _leer("static", "js", "global.js")
    assert "data-click-args='${UX.esc(JSON.stringify([String(o.id_meli_sugerido), String(o.titulo_sugerido)]))}'" in js
    assert "titulo_sugerido.replace(" not in js


# ── 28, 29, 33, 46. Un botón primario con sentido por pantalla ─────────────────────────────────────────────────────────────────────────────
def test_los_filtros_y_las_busquedas_son_secundarios():
    for plantilla, texto in (("costos.html", "Ver período"), ("precios.html", "Recalcular"), ("tendencias.html", "Buscar"), ("metricas.html", "Ver período")):
        assert f'class="btn btn-secondary">{texto}</button>' in _leer("templates", plantilla), plantilla


def test_las_acciones_opcionales_de_una_lista_no_son_primarias():
    assert "opcional: 'btn-secondary'" in _leer("static", "js", "ux.js")
    assert "else 'btn-secondary'" in _leer("templates", "_dia_pendientes.html") or "'btn-secondary')" in _leer("templates", "_dia_pendientes.html")


def test_el_dashboard_manda_a_revisar_ventas_cuando_hay_perdida():
    t = _leer("templates", "dashboard_personalizable.html")
    assert "{ href: '/metricas', clase: 'btn-primary', texto: 'Revisar ventas' }" in t and "{ href: '/costos', clase: 'btn-primary', texto: 'Cargar los costos' }" in t


def test_un_despacho_vacio_tiene_puerta_de_salida_y_un_solo_primario():
    t = _leer("templates", "_dia_despacho.html")
    assert '"Revisar ventas", "/metricas") }}' in t                                                          # el CTA de la macro vacio()
    vacio = re.search(r'\{% else %\}\s*<div class="flex-gap no-imprimir" style="margin-bottom:16px;">.*?</div>', t, re.S).group(0)         # la rama «sin paquetes» del encabezado
    assert 'class="btn btn-secondary"' in vacio and "btn-primary" not in vacio


def test_monotributo_tiene_un_solo_primario_por_estado():
    t = _leer("templates", "monotributo.html")
    assert t.count("btn-primary") == 1 and 'btn btn-primary btn-lg' in t                                       # «Guardar categoría»; el otro estado usa el formulario de condición fiscal


# ── 31, 48, 50. Contraste y animaciones ────────────────────────────────────────────────────────────────────────────────────────────────────
def _luz(hexa):
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4                               # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contraste(a, b):
    la, lb = sorted((_luz(a), _luz(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _tokens(bloque):
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b", bloque))


def test_el_gris_de_los_textos_de_ayuda_se_lee_en_los_dos_temas():
    css = _leer("static", "css", "style.css")
    oscuro = _tokens(css[css.index(":root {"):css.index("}", css.index(":root {"))])
    claro_ini = css.index(':root[data-theme="light"]')
    claro = _tokens(css[claro_ini:css.index("}", claro_ini)])
    for tema, tokens, fondos in (("oscuro", oscuro, ("--bg-base", "--bg-surface", "--glass-bg")), ("claro", claro, ("--bg-base", "--bg-surface"))):
        for fondo in fondos:
            assert fondo in tokens and "--text-faint" in tokens, (tema, fondo)
            assert _contraste(tokens["--text-faint"], tokens[fondo]) >= 4.5, (tema, fondo, _contraste(tokens["--text-faint"], tokens[fondo]))


def test_el_placeholder_y_el_campo_deshabilitado_usan_ese_gris_sin_opacidad_extra():
    css = _leer("static", "css", "style.css")
    assert "::placeholder, input:disabled::placeholder, textarea:disabled::placeholder { color: var(--text-faint); opacity: 1; }" in css
    assert "input:disabled { color: var(--text-faint); -webkit-text-fill-color: currentColor; opacity: 1; }" in css


def test_el_circulo_de_despachado_se_ve_en_un_deposito_con_poca_luz():
    css = _leer("static", "css", "ux.css")
    regla = re.search(r"\.despacho-item:not\(\.despachado\) \.despacho-check \{[^}]*border-width: 3px[^}]*background: color-mix[^}]*box-shadow[^}]*\}", css)
    assert regla and "var(--semantic-warning)" in regla.group(0)


def test_solo_late_el_primer_aviso_urgente_y_los_contadores_del_menu_no_laten():
    ux, estilo = _leer("static", "css", "ux.css"), _leer("static", "css", "style.css")
    assert ".ux-item-accion.ux-danger ~ .ux-item-accion.ux-danger { animation: none; }" in ux
    insignia = estilo[estilo.index(".nav-badge {"):estilo.index("}", estilo.index(".nav-badge {"))]
    assert "animation" not in insignia
    assert "pulseCurva 1.8s infinite" not in estilo.split("@keyframes pulseCurva")[0].split(".badge-curva-rota")[1]


# ── 51. Capas: el aviso (toast) por encima de los menús y modales ──────────────────────────────────────────────────────────────────────────
def test_el_toast_queda_por_encima_del_menu_movil_el_buscador_y_los_modales():
    estilo, shell = _leer("static", "css", "style.css"), _leer("static", "css", "shell.css")
    z = lambda texto, selector: int(re.search(re.escape(selector) + r"[^{]*\{[^}]*?z-index:\s*(\d+)", texto).group(1))      # noqa: E731
    toast = z(estilo, "#toast-container")
    assert toast > z(shell, ".sidebar-overlay") and toast > z(estilo, ".command-overlay") and toast > z(estilo, "#tour-capa")
    assert toast > int(re.search(r"\.sidebar \{ transform: translateX\(-100%\);[^}]*z-index: (\d+)", shell).group(1))        # el menú lateral abierto en el celular (8600)


# ── Ratchet de manejadores inline: lo que quedó migrado no puede volver ────────────────────────────────────────────────────────────────────
def test_el_layout_no_tiene_manejadores_inline():
    # Desde el 2026-10-08 NINGUNA plantilla los tiene (test_correcciones_frontend::test_ninguna_pantalla_tiene_manejadores_en_el_html): acá queda el layout, que todas heredan.
    from tests.test_correcciones_frontend import INLINE
    assert not INLINE.search(_leer("templates", "base.html"))


# ── 54. El PDF de Ganancia Real no sale cortado ────────────────────────────────────────────────────────────────────────────────────────────
def test_las_filas_que_el_ver_mas_esconde_solo_se_esconden_en_pantalla_y_salen_en_el_pdf():
    css = _leer("static", "css", "style.css")
    assert "@media screen { .oculto-mostrar-mas { display: none !important; } }" in css
    assert re.search(r"(?m)^\.oculto-mostrar-mas \{ display: none", css) is None                              # ya no hay una regla que lo esconda también al imprimir
    imprimir = css[css.index("@media print {"):]
    assert '[data-click="mostrarMasGenerico"], .ux-toggle-variantes { display: none !important; }' in imprimir
    # el historial y el ranking de modelos de Ganancia Real son los que se recortan con «Ver más»: siguen usando esa clase
    t = _leer("templates", "metricas.html")
    assert t.count("oculto-mostrar-mas") >= 2 and 'data-click="mostrarMasGenerico"' in t

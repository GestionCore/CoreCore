"""
Segunda auditoría externa (frontend, 19 puntos). Cada punto se verificó contra el código y la base real antes de tocarlo: acá quedan las pruebas de lo que SÍ estaba mal
y de lo que se endureció, más el despachador de eventos (`data-click`) que reemplaza a los `onclick` inline.
"""
import glob
import html as html_lib
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")
CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
PLANTILLAS = sorted(glob.glob(os.path.join(RAIZ, "templates", "*.html")))
INLINE = re.compile(r"\son(?:click|change|input|keyup|keydown|submit|mouseover|mouseout|focus|blur|load|error)=\"")

# Pantallas ya migradas a data-click: no pueden volver a tener un manejador escrito en el HTML.
SIN_INLINE = ("_ux.html", "metricas.html", "stock_masivo.html", "_dia_despacho.html", "dashboard_personalizable.html")
# Tope de manejadores inline que quedan (plantillas + global.js). Solo puede BAJAR: al migrar otra pantalla se baja el número. Es el camino para sacar 'unsafe-inline' del script-src.
PRESUPUESTO_INLINE = 143


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── 11. Menos onclick inline, más data-click ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_las_pantallas_migradas_no_tienen_manejadores_en_el_html():
    for nombre in SIN_INLINE:
        assert not INLINE.search(_leer("templates", nombre)), nombre


def test_los_manejadores_inline_que_quedan_no_aumentan():
    total = sum(len(INLINE.findall(_leer("templates", os.path.basename(r)))) for r in PLANTILLAS) + len(INLINE.findall(_leer("static", "js", "global.js")))
    assert total <= PRESUPUESTO_INLINE, f"Hay {total} manejadores inline (tope {PRESUPUESTO_INLINE}): usá data-click (ver static/js/ux.js). Si migraste pantallas, bajá el tope."


def test_cada_data_click_llama_a_una_funcion_que_existe():
    fuente = "\n".join(_leer("static", "js", os.path.basename(r)) for r in glob.glob(os.path.join(RAIZ, "static", "js", "*.js"))) + "\n" + "\n".join(_leer("templates", os.path.basename(r)) for r in PLANTILLAS)
    definidas = (set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", fuente)) | set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", fuente))
                 | set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", fuente)))
    faltan = {}
    for ruta in PLANTILLAS:
        for evento, nombre in re.findall(r'\bdata-(click|change|input|keyup)="([A-Za-z_$][\w$.]*)"', _leer("templates", os.path.basename(ruta))):
            base = nombre.split(".")[0]
            if base not in definidas and base != "window":
                faltan.setdefault(base, set()).add(os.path.basename(ruta))
    assert not faltan, {k: sorted(v) for k, v in faltan.items()}


def test_los_argumentos_escritos_a_mano_son_json_valido():
    for ruta in PLANTILLAS:
        for args in re.findall(r"data-(?:click|change|input|keyup)-args='([^']*)'", _leer("templates", os.path.basename(ruta))):
            if "{{" in args:
                continue                                                      # los armados con Jinja se prueban renderizados
            json.loads(args)


# El despachador se ejecuta de verdad con node, contra elementos de mentira (no hay DOM): lo que se prueba es la lógica de buscar, resolver y llamar.
def _correr_ux(codigo, tmp_path):
    ruta = os.path.join(RAIZ, "static", "js", "ux.js").replace("\\", "/")
    guion = tmp_path / "ux_prueba.js"
    guion.write_text("""
const fs = require('fs'), vm = require('vm');
const oyentes = {}, errores = [], llamadas = [];
const caja = { console: { error: (...a) => errores.push(a.join(' ')), log() {} }, document: { addEventListener: (t, f) => { (oyentes[t] = oyentes[t] || []).push(f); }, querySelectorAll: () => [] } };
caja.window = caja; caja.addEventListener = () => {};
vm.createContext(caja);
vm.runInContext(fs.readFileSync(%s, 'utf8'), caja);
function elemento(attrs, padre, extra) {
  const e = Object.assign({ nodeType: 1, tagName: 'DIV', parentElement: padre || null, value: 'v', form: { id: 'f' }, clases: [],
    hasAttribute(a) { return a in attrs; }, getAttribute(a) { return a in attrs ? attrs[a] : null; },
    closest(sel) { let x = this; while (x) { if (x.clases.includes(sel.slice(1))) return x; x = x.parentElement; } return null; },
    click() { disparar('click', this); } }, extra || {});
  return e;
}
function disparar(tipo, objetivo, tecla) { (oyentes[tipo] || []).forEach(f => f({ type: tipo, target: objetivo, key: tecla, preventDefault() { llamadas.push('preventDefault'); } })); }
%s
""" % (json.dumps(ruta), codigo), encoding="utf-8")
    r = subprocess.run(["node", str(guion)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    return json.loads(r.stdout)


@CON_NODE
def test_el_despachador_llama_a_la_funcion_con_sus_argumentos_y_el_elemento(tmp_path):
    r = _correr_ux("""
      caja.paso = (boton, delta) => llamadas.push(['paso', boton.id, delta]);
      const boton = elemento({ 'data-click': 'paso', 'data-click-args': '["$el", -1]' }, null, { id: 'b1' });
      disparar('click', boton);
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == [["paso", "b1", -1]]


@CON_NODE
def test_una_ruta_con_puntos_se_llama_con_su_objeto_como_this(tmp_path):
    r = _correr_ux("""
      caja.RangoFechas = { marca: 'objeto', toggle(id) { llamadas.push([this.marca, id]); } };
      caja.marca = 'ventana'; caja.print = function () { llamadas.push(['print', this.marca]); };
      disparar('click', elemento({ 'data-click': 'RangoFechas.toggle', 'data-click-args': '["rango"]' }));
      disparar('click', elemento({ 'data-click': 'window.print' }));
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == [["objeto", "rango"], ["print", "ventana"]]


@CON_NODE
def test_los_argumentos_especiales_se_resuelven(tmp_path):
    r = _correr_ux("""
      const item = elemento({}, null, { clases: ['despacho-item'], id: 'item' });
      const boton = elemento({ 'data-click': 'f', 'data-click-args': '["$closest:.despacho-item", "$valor", "$form", "$ev", "texto", 3]' }, item, { value: 'abc' });
      caja.f = (...a) => llamadas.push([a[0].id, a[1], a[2].id, a[3].type, a[4], a[5]]);
      disparar('click', boton);
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == [["item", "abc", "f", "click", "texto", 3]]


@CON_NODE
def test_data_aislar_frena_el_click_hacia_los_de_afuera_pero_no_a_los_de_adentro(tmp_path):
    r = _correr_ux("""
      caja.afuera = () => llamadas.push('afuera'); caja.adentro = () => llamadas.push('adentro');
      const contenedor = elemento({ 'data-click': 'afuera' });
      const aislado = elemento({ 'data-aislar': '' }, contenedor);
      const texto = elemento({}, aislado);
      const boton = elemento({ 'data-click': 'adentro' }, aislado);
      disparar('click', texto);           // un click en un texto dentro del aislado NO activa el de afuera
      disparar('click', boton);           // el botón de adentro sí hace lo suyo
      disparar('click', elemento({}, contenedor));   // fuera del aislado, el contenedor responde
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == ["adentro", "afuera"]


@CON_NODE
def test_el_mas_cercano_gana_y_los_otros_eventos_usan_su_propio_atributo(tmp_path):
    r = _correr_ux("""
      caja.cerca = () => llamadas.push('cerca'); caja.lejos = () => llamadas.push('lejos'); caja.alCambiar = (v) => llamadas.push(['cambio', v]);
      const padre = elemento({ 'data-click': 'lejos' });
      disparar('click', elemento({ 'data-click': 'cerca' }, padre));
      disparar('change', elemento({ 'data-change': 'alCambiar', 'data-change-args': '["$valor"]' }, null, { value: '7' }));
      disparar('input', elemento({ 'data-change': 'alCambiar' }));      // un input no activa data-change
      process.stdout.write(JSON.stringify(llamadas));
    """, tmp_path)
    assert r == ["cerca", ["cambio", "7"]]


@CON_NODE
def test_un_elemento_con_role_button_se_activa_con_enter_y_espacio_pero_un_boton_de_verdad_no_se_duplica(tmp_path):
    r = _correr_ux("""
      caja.abrir = () => llamadas.push('abrir');
      const cab = elemento({ role: 'button', 'data-click': 'abrir' });
      disparar('keydown', cab, 'Enter'); disparar('keydown', cab, ' '); disparar('keydown', cab, 'a');
      const boton = elemento({ role: 'button', 'data-click': 'abrir' }, null, { tagName: 'BUTTON' });
      disparar('keydown', boton, 'Enter');
      process.stdout.write(JSON.stringify(llamadas.filter(x => x === 'abrir')));
    """, tmp_path)
    assert r == ["abrir", "abrir"]


@CON_NODE
def test_una_funcion_inexistente_o_un_json_roto_avisan_en_consola_y_no_rompen_nada(tmp_path):
    r = _correr_ux("""
      disparar('click', elemento({ 'data-click': 'noExiste' }));
      caja.f = () => llamadas.push('f');
      disparar('click', elemento({ 'data-click': 'f', 'data-click-args': '[roto' }));
      process.stdout.write(JSON.stringify({ errores: errores.length, llamadas }));
    """, tmp_path)
    assert r == {"errores": 2, "llamadas": []}


# ── 1, 2. Un solo botón primario con sentido ────────────────────────────────────────────────────────────────────────────────────────────────
def test_ganancia_real_tiene_un_solo_boton_primario_y_es_la_descarga_debajo_del_numero():
    t = _leer("templates", "metricas.html")
    assert t.count("btn-primary") == 1 and 'btn btn-secondary">Ver período' in t
    hero = t[t.index('<div class="ux-hero ux-{{ tono }}">'):t.index("<!-- ── 2. QUÉ REVISAR")]
    assert 'class="btn btn-primary" data-click="window.print"' in hero and "no-imprimir" in hero
    assert '"Ver detalle", "#seccion-reclamos", "btn-secondary")' in t                  # el aviso informativo no es un segundo primario (el urgente va en rojo)


def test_el_dashboard_da_una_salida_desde_el_numero_segun_el_estado():
    t = _leer("templates", "dashboard_personalizable.html")
    assert 'id="hero-acciones"' in t
    # sin costo → /costos primario; en pérdida → /metricas primario; bien → /metricas secundario
    assert "{ href: '/costos', clase: 'btn-primary'" in t and "negativo ? { href: '/metricas', clase: 'btn-primary'" in t and "{ href: '/metricas', clase: 'btn-secondary'" in t
    assert t.index("sinCosto ?") < t.index("(negativo ? {")                            # arreglar el dato que falsea el número va antes que mirar la pérdida


# ── 3, 15. Stock masivo ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_stock_masivo_no_compite_con_el_boton_de_aplicar_y_el_acordeon_se_maneja_con_teclado():
    t = _leer("templates", "stock_masivo.html")
    assert 'ux-pill ux-accion" style="padding:1px 8px;"' not in t and "ux-neutral ux-pill-suave\" style=\"padding:1px 8px;\">{{ editables|length }}" in t
    cab = re.search(r'<div class="acordeon-header"[^>]*>', t).group(0)
    assert 'role="button"' in cab and 'tabindex="0"' in cab and 'aria-expanded="false"' in cab and 'data-click="toggleAcordeon"' in cab
    assert "setAttribute('aria-expanded'" in t                                       # y se mantiene al abrir y cerrar


def test_stock_masivo_envia_solo_los_campos_que_cambiaron():
    t = _leer("templates", "stock_masivo.html")
    assert "function soloLoQueCambio()" in t and "_formStock.submit = function ()" in t
    cuerpo = t[t.index("function soloLoQueCambio()"):t.index("// Avisa antes de irse")]
    assert "i.value !== i.dataset.original) return" in cuerpo                       # los cambiados quedan habilitados
    assert "input[type=\"hidden\"]" in cuerpo and "pageshow" in cuerpo                 # el par orig_ se va con su stock_, y volver con «Atrás» los rehabilita


# ── 6, 16. Dashboard ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_dashboard_destruye_los_graficos_que_rearma_y_las_promesas_no_se_envenenan():
    t = _leer("templates", "dashboard_personalizable.html")
    assert "function _destruirGrafico(" in t and "_graficos.tendencia = new Chart(" in t and "_graficos.ganancia14d = new Chart(" in t
    assert t.count("_destruirGrafico('tendencia')") >= 2                              # al empezar a rearmar los widgets y justo antes de crear el gráfico
    assert "delete _compartidas[clave]" in t                                         # el error no queda guardado
    assert not re.search(r"let _\w+PromiseCache = null", t)
    assert "turno !== _turnoWidgets" in t                                            # una respuesta vieja no pinta sobre una pantalla ya rearmada


# ── 8, 12. Despacho ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_despacho_usa_la_hora_de_argentina_y_no_la_de_la_pc():
    t = _leer("templates", "_dia_despacho.html")
    assert "toLocaleDateString('sv-SE')" not in t and "timeZone: ZONA_ARGENTINA" in t
    assert "America/Argentina/Buenos_Aires" in t and "corte.setHours" not in t and "new Date(), corte" not in t
    assert "const ES_HOY = '{{ fecha }}' === ahoraArgentina().fecha;" in t


@CON_BASE
def test_marcar_despachado_nunca_manda_la_palabra_none_aunque_la_variante_venga_nula():
    import app as aplicacion
    from tests.test_dia_a_dia import CONTEXTO
    paquete = dict(clave="1-MLA1-", id_orden=1001, id_meli="MLA1", id_variante=None, modelo="Termo", thumbnail=None, talle="Único", cantidad=1, comprador_nombre="Ana",
                   comprador_nickname="ana", tipo_envio="Flex", limite_texto=None, limite_tono="info", despachado=False, etiqueta_impresa=False, flex_zona=None, flex_zona_meli=None)
    contexto = dict(CONTEXTO, paquetes=[paquete], total=1, flex_habilitado=True, umbrales_flex=[dict(id=1, etiqueta="CABA", precio=1000, neto=900)])
    with aplicacion.app.test_request_context("/dia"):
        pagina = aplicacion.render_template("dia.html", active_nav="despacho", errores={}, **contexto)
    seccion = pagina.split('id="despacho"')[1].split("</section>")[0]
    assert "None" not in seccion                                                                                 # ni en los atributos ni en el texto de la sección
    argumentos = [json.loads(html_lib.unescape(a)) for a in re.findall(r"data-click-args='([^']*)'", pagina)]
    toggles = [a for a in argumentos if a and a[0] == "$closest:.despacho-item"]
    assert len(toggles) == 2 and all(a == ["$closest:.despacho-item", "1001", "MLA1", ""] for a in toggles)       # los ids viajan como texto, la variante vacía como ""
    assert ["1001", 1] in argumentos and ["1001", 0] in argumentos                                               # zonas de Flex


# ── 10, 14, 18. Ganancia Real: gráficos y margen ────────────────────────────────────────────────────────────────────────────────────────────
def test_los_graficos_de_ganancia_real_esperan_tamano_real_y_siguen_el_tema():
    t = _leer("templates", "metricas.html")
    assert "requestAnimationFrame(" not in t and "function _cuandoTengaTamano(" in t and "new ResizeObserver(" in t
    assert "const _TOOLTIP" not in t and "..._TOOLTIP" not in t and t.count("..._tooltip()") == 3
    assert "rgba(18,21,48" not in t and "#f7f7ff" not in t and "rgba(255,255,255,0.05)" not in t
    for ficha in ("--glass-bg-alt", "--glass-border", "--text-primary"):
        assert ficha in t
    assert "bodyColor: e.texto" in t                                                 # el texto del cuerpo ya no es el blanco fijo de Chart.js


def test_un_modelo_sin_facturado_pero_con_neto_negativo_es_una_perdida_no_un_cero():
    t = _leer("templates", "metricas.html")
    assert "else (-100 if c.raw.neto_total < 0 else 0)" in t


# ── 17, 19. CSS ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_css_del_modo_foco_ya_no_apunta_a_un_form_que_no_existe():
    css = _leer("static", "css", "style.css")
    assert 'form[action="/despacho"]' not in css
    ux = _leer("static", "css", "ux.css")
    assert re.search(r"body\.modo-despacho-limpio \.ux-periodo[^{]*\{\s*display: none !important", ux)            # lo que sí lo esconde: el form de «Ver otro día» es un .ux-periodo


def test_la_ventana_del_asistente_entra_en_una_pantalla_de_celular():
    css = _leer("static", "css", "shell.css")
    regla = re.search(r"\.chat-window \{[^}]*\}", css).group(0)
    assert "width: min(390px, calc(100vw - 24px))" in regla and "right: 12px" in regla and "calc(var(--bottombar-h) + 76px)" in regla


def test_el_teclado_no_alterna_dos_veces_un_panel_colapsable_con_data_click():
    """El checklist del Dashboard tenía un onkeydown inline Y el listener de global.js: cada Enter lo abría y lo cerraba (efecto neto: nada). Ahora lo atiende uno solo."""
    js = _leer("static", "js", "global.js")
    assert "if (!e.defaultPrevented && (e.key === 'Enter' || e.key === ' ') && e.target.matches('.panel-colapsable[role=\"button\"]'))" in js
    assert "onkeydown" not in _leer("templates", "dashboard_personalizable.html")

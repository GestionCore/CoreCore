"""
Costos por modelo → variante → talle (costos.agrupar_modelos y la pantalla /costos).
Se carga UN costo por modelo (todos sus colores y talles) o por variante (un color); el costo por talle solo cuando de verdad cambia. El costo se sigue guardando por publicación:
esto solo decide cómo se ofrece cargarlo, sin suponer el rubro (la variante es lo que distingue a los títulos de una misma familia de Mercado Libre, no «el color»).
Los casos salen de las cuentas reales (2026-10-12): 192 publicaciones → 21 modelos y 83 → 10.
"""
import json
import os
import shutil
import subprocess

import pytest

import costos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pub(id_, titulo, familia, costo=0.0, estado="active", talle=None, precio=30000.0, comision=2000.0, envio=1500.0, thumbnail=None, etiqueta=None):
    from utils import limpiar_titulo_modelo, normalizar_talle
    ganancia = precio - comision - envio - costo
    return {"id": id_, "titulo": titulo, "precio_costo": costo, "precio_costo_formateado": "0", "estado": estado, "thumbnail": thumbnail, "precio": precio, "comision": comision, "envio": envio,
            "precio_formateado": "10.000", "ganancia_negativa": costo > 0 and ganancia < 0, "modelo": limpiar_titulo_modelo(titulo, talle) or titulo,
            "talle": normalizar_talle(talle), "etiqueta": etiqueta, "familia": familia}


def _buzo(color, talles, **kw):
    return [_pub(f"{color}{t}", f"Buzo Manta Mujer Largo Abrigo {color} Liso {t}", "F1", talle=t, **kw) for t in talles]


# ── Nombre y etiqueta de cada variante ──────────────────────────────────────────────────────────────────────────────────────

def test_las_variantes_se_distinguen_por_las_palabras_que_no_comparten():
    nombre, etiquetas = costos.nombres_de_variantes(["Buzo Manta Mujer Beige Liso", "Buzo Manta Mujer Gris Liso", "Buzo Manta Mujer Rosa Liso"])
    assert nombre == "Buzo Manta Mujer Liso"
    assert etiquetas == {"Buzo Manta Mujer Beige Liso": "Beige", "Buzo Manta Mujer Gris Liso": "Gris", "Buzo Manta Mujer Rosa Liso": "Rosa"}


def test_con_una_sola_variante_no_hay_nada_que_distinguir():
    assert costos.nombres_de_variantes(["Termo Acero 1l Negro"]) == ("Termo Acero 1l Negro", {"Termo Acero 1l Negro": ""})
    assert costos.nombres_de_variantes([]) == ("", {})


def test_la_misma_palabra_en_otra_mayuscula_no_cuenta_como_distinta():
    nombre, etiquetas = costos.nombres_de_variantes(["Funda Iphone 13 NEGRA", "Funda iphone 13 Azul"])
    assert nombre == "Funda Iphone 13" and sorted(etiquetas.values()) == ["Azul", "NEGRA"]


def test_si_los_titulos_tienen_las_mismas_palabras_en_otro_orden_no_se_inventa_una_etiqueta():
    _, etiquetas = costos.nombres_de_variantes(["Pantalon Azul Liso Pre Lavado", "Pantalon Azul Pre Lavado Liso"])
    assert etiquetas == {"Pantalon Azul Liso Pre Lavado": "Pantalon Azul Liso Pre Lavado", "Pantalon Azul Pre Lavado Liso": "Pantalon Azul Pre Lavado Liso"}       # el título entero


# ── Agrupado ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_una_familia_con_tres_colores_y_dos_talles_es_un_modelo_con_tres_variantes():
    productos = _buzo("Beige", ["2", "3"], costo=13000.0) + _buzo("Gris", ["2", "3"], costo=13000.0) + _buzo("Rosa", ["2", "3"])
    (m,) = costos.agrupar_modelos(productos)
    assert (m["n_variantes"], m["n_publicaciones"], m["n_activas"]) == (3, 6, 6)
    assert m["nombre"] == "Buzo Manta Mujer Largo Abrigo Liso"
    assert sorted(v["etiqueta"] for v in m["variantes"]) == ["Beige", "Gris", "Rosa"]
    assert m["sin_costo"] == 2 and m["costo_min"] == 13000.0 and m["costo_max"] == 13000.0
    assert m["costo_comun"] is None                                                         # no todas valen lo mismo: el campo del modelo dice «Varios costos»
    assert m["a_atender"] is True                                                           # algunas cargadas y otras no: quedó a medias
    rosa = next(v for v in m["variantes"] if v["etiqueta"] == "Rosa")
    beige = next(v for v in m["variantes"] if v["etiqueta"] == "Beige")
    assert rosa["sin_costo"] == 2 and rosa["costo_comun"] is None and beige["costo_comun"] == 13000.0 and beige["a_atender"] is False


def test_un_costo_igual_en_todas_las_activas_se_muestra_en_el_campo_aunque_alguna_pausada_difiera():
    productos = _buzo("Beige", ["2", "3"], costo=13000.0) + [_pub("p", "Buzo Manta Mujer Largo Abrigo Beige Liso 4", "F1", costo=9000.0, estado="paused", talle="4")]
    (m,) = costos.agrupar_modelos(productos)
    assert m["costo_comun"] == 13000.0 and m["n_activas"] == 2 and m["sin_costo"] == 0 and m["costo_min"] == 9000.0 and m["costo_max"] == 13000.0


def test_una_publicacion_pausada_sin_costo_no_cuenta_como_falta():
    productos = _buzo("Beige", ["2"], costo=13000.0) + [_pub("p", "Buzo Manta Mujer Largo Abrigo Beige Liso 3", "F1", costo=0.0, estado="paused", talle="3")]
    (m,) = costos.agrupar_modelos(productos)
    assert m["sin_costo"] == 0 and m["a_atender"] is False


def test_si_el_titulo_trae_el_talle_en_el_medio_son_talles_de_una_variante_y_no_variantes():
    # «… Azul 2 Denim», «… Azul 3 Denim»: lo único que cambia es un talle escrito en medio del título (caso real de la cuenta 7)
    productos = [_pub(f"a{t}", f"Campera De Jean Mujer Azul Premium Azul {t} Denim", "F9", costo=12000.0) for t in ("2", "3", "4", "5")]
    (m,) = costos.agrupar_modelos(productos)
    assert m["n_variantes"] == 1 and m["n_publicaciones"] == 4
    assert [p["rotulo"] for p in m["variantes"][0]["filas"]] == ["2", "3", "4", "5"]         # la fila dice qué talle es, no «Único»


def test_una_diferencia_que_no_es_un_talle_sigue_siendo_una_variante():
    productos = [_pub("a", "Termo Acero 1l Negro Liso", "F2"), _pub("b", "Termo Acero 1l Verde Liso", "F2"), _pub("c", "Termo Acero 1l 2 Liso", "F2")]
    (m,) = costos.agrupar_modelos(productos)
    assert m["n_variantes"] == 3                                                              # «Negro» y «Verde» no son talles: no se fusiona nada


def test_sin_familia_cada_titulo_es_su_propio_modelo():
    productos = [_pub("a", "Gorra Lisa Negra", None), _pub("b", "Gorra Lisa Azul", None), _pub("c", "Gorra Lisa Azul", None)]
    modelos = costos.agrupar_modelos(productos)
    assert sorted((m["nombre"], m["n_publicaciones"]) for m in modelos) == [("Gorra Lisa Azul", 2), ("Gorra Lisa Negra", 1)]


def test_el_orden_pone_primero_lo_que_falta_cargar_y_al_final_lo_pausado():
    productos = (_pub_modelo("Zapatilla A", costo=5000.0, n=2) + _pub_modelo("Zapatilla B", costo=0.0, n=3) + _pub_modelo("Zapatilla C", costo=0.0, n=1)
                 + _pub_modelo("Zapatilla D", costo=0.0, n=2, estado="paused"))
    assert [m["nombre"] for m in costos.agrupar_modelos(productos)] == ["Zapatilla B", "Zapatilla C", "Zapatilla A", "Zapatilla D"]


def _pub_modelo(nombre, costo, n, estado="active"):
    return [_pub(f"{nombre}{i}", f"{nombre} {i + 36}", f"fam-{nombre}", costo=costo, estado=estado, talle=str(i + 36)) for i in range(n)]


def test_una_que_pierde_plata_se_marca_para_atender_aunque_todas_tengan_costo():
    productos = [_pub("a", "Remera Lisa 2", "F3", costo=7000.0), _pub("b", "Remera Lisa 3", "F3", costo=7000.0, precio=9000.0)]          # b: 9.000 − 2.000 − 1.500 − 7.000 < 0
    (m,) = costos.agrupar_modelos(productos)
    assert m["sin_costo"] == 0 and m["a_atender"] is True


def test_no_se_pierde_ni_se_repite_ninguna_publicacion():
    productos = _buzo("Beige", ["2", "3"]) + _buzo("Gris", ["2", "3"]) + [_pub("sola", "Gorra Lisa", None)] + _pub_modelo("Zapatilla", 5000.0, 3)
    modelos = costos.agrupar_modelos(productos)
    ids = [p["id"] for m in modelos for p in m["filas"]]
    assert sorted(ids) == sorted(p["id"] for p in productos) and len(ids) == len(set(ids))
    for m in modelos:
        assert sorted(p["id"] for v in m["variantes"] for p in v["filas"]) == sorted(p["id"] for p in m["filas"])        # variantes y modelo suman lo mismo


def test_agrupar_no_modifica_los_datos_de_entrada():
    productos = _buzo("Beige", ["2"])
    copia = json.loads(json.dumps(productos))
    costos.agrupar_modelos(productos)
    assert productos == copia and "rotulo" not in productos[0]


def test_la_consulta_trae_la_familia_de_cada_publicacion():
    import inspect
    fuente = inspect.getsource(costos.obtener_datos_costos)
    assert "p.family_id" in fuente and '"familia": fila.get("family_id") or None' in fuente


# ── La pantalla ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def renderizar():
    import app as modulo_app
    from flask import render_template

    def _render(**contexto):
        with modulo_app.app.test_request_context("/costos"):
            return render_template("costos.html", **contexto)
    return _render


def _contexto(productos):
    return dict(gastos=[], stats={"fijos": "0", "variables": "0", "total": "0", "fijos_raw": 0, "variables_raw": 0}, productos=productos, modelos=costos.agrupar_modelos(productos),
                fecha_desde="2026-10-01", fecha_hasta="2026-10-12", flex_data={"umbrales": [], "zonas": [], "origen": None, "reintegro_pct": 10, "vista_previa": {"umbrales": [], "ordenes": 0, "costo_total": 0, "sin_precio": 0}},
                flex_pendientes_n=0, hay_flex=False, active_nav="costos")


def test_la_pantalla_ofrece_un_campo_por_modelo_y_otro_por_variante_y_conserva_un_campo_por_publicacion(renderizar):
    productos = _buzo("Beige", ["2", "3"], costo=13000.0) + _buzo("Gris", ["2", "3"]) + _pub_modelo("Zapatilla", 5000.0, 3) + [_pub("sola", "Gorra Lisa Roja", None, costo=3000.0)]
    html = renderizar(**_contexto(productos))
    assert html.count('class="input-costo-producto"') == len(productos)                          # lo que se guarda sigue siendo UN costo por publicación
    assert html.count('class="input-costo-grupo"') == 1 + 2 + 1                                  # el modelo del buzo + sus 2 variantes (de 2 talles) + el modelo Zapatilla (3 talles); la gorra sola no lleva campo de grupo
    assert html.count('ux-grupo-costo ux-variante-costo') == 2 and 'ux-grupo-costo ux-modelo-costo' in html
    assert "Ajustar por variante" in html and "Ajustar por talle" in html
    assert 'value="13000"' in html and "13000.0" not in html                                    # sin «,0» de más
    assert "input-costo-modelo" not in html                                                      # el campo viejo ya no existe


def test_si_la_cuenta_no_vende_con_talles_las_filas_son_publicaciones(renderizar):
    productos = [_pub("a", "Funda Celular Negra", "F7", talle="Único"), _pub("b", "Funda Celular Negra", "F7", talle="Único")]
    contexto = _contexto(productos)
    with __import__("app").app.test_request_context("/costos"):
        from flask import render_template
        import utils
        html = render_template("costos.html", **{**contexto, "vocab": utils.vocabulario(False)})
    assert "Ajustar por publicación" in html and "Ajustar por talle" not in html


def test_un_modelo_de_una_sola_publicacion_no_lleva_campo_de_grupo(renderizar):
    html = renderizar(**_contexto([_pub("sola", "Gorra Lisa Roja", None, thumbnail="http://x/g.jpg")]))
    assert html.count('class="input-costo-producto"') == 1 and 'input-costo-grupo' not in html.replace(".input-costo-grupo", "")


def test_los_titulos_de_terceros_se_escapan_en_la_pantalla(renderizar):
    html = renderizar(**_contexto([_pub("x", "Campera <script>alert(1)</script> Negra 2", "F8"), _pub("y", "Campera <script>alert(1)</script> Negra 3", "F8")]))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_guardar_confirma_antes_de_pisar_un_costo_ya_cargado():
    fuente = open(os.path.join(RAIZ, "templates", "costos.html"), encoding="utf-8").read()
    assert "await confirmarDecision(" in fuente and "que ya tenían uno" in fuente and "'Antes: ' + rango(antes)" in fuente


# ── El resumen en vivo de cada grupo (JavaScript, con node) ─────────────────────────────────────────────────────────────────

CON_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")


def _funcion_js(fuente, nombre):
    i = fuente.index(f"function {nombre}(")
    j = fuente.index("{", i)
    prof = 0
    for k in range(j, len(fuente)):
        prof += fuente[k] == "{"
        prof -= fuente[k] == "}"
        if prof == 0:
            return fuente[i:k + 1]


def _resumen(filas, margen_minimo=15):
    """filas: [(activa, costo, precio, comision, envio)] → (clase, texto) que pinta pintarResumen."""
    fuente = open(os.path.join(RAIZ, "templates", "costos.html"), encoding="utf-8").read()
    programa = f"""
global.window = {{ MARGEN_MINIMO: {margen_minimo} }};
global.UX = {{ plata: (n) => '$' + Math.round(n).toLocaleString('es-AR') }};
const filas = {json.dumps([{"activa": a, "costo": c, "precio": p, "comision": co, "envio": e} for a, c, p, co, e in filas])}.map(f => ({{
  dataset: {{ activa: f.activa ? '1' : '0', precio: String(f.precio), comision: f.comision === null ? '' : String(f.comision), envio: String(f.envio) }},
  querySelector: () => ({{ value: f.costo === null ? '' : String(f.costo) }}) }}));
const marca = {{ className: '', textContent: '' }};
const grupo = {{ querySelector: () => marca, querySelectorAll: () => filas }};
{_funcion_js(fuente, "pintarResumen")}
pintarResumen(grupo);
console.log(JSON.stringify([marca.className, marca.textContent]));
"""
    r = subprocess.run(["node", "-e", programa], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@CON_NODE
def test_el_resumen_avisa_primero_lo_que_falta_cargar():
    clase, texto = _resumen([(True, 0, 10000, 2000, 1500), (True, 4000, 10000, 2000, 1500), (False, 0, 10000, 2000, 1500)])          # la pausada sin costo no cuenta
    assert texto == "1 sin costo" and "ux-warn" in clase


@CON_NODE
def test_el_resumen_cuenta_las_que_pierden_plata():
    # 10.000 − 2.000 − 1.500 = 6.500 de margen antes del costo: con $6.000 queda +500; con $9.000 y $9.500 se pierde
    assert _resumen([(True, 6000, 10000, 2000, 1500), (True, 9000, 10000, 2000, 1500), (True, 9500, 10000, 2000, 1500)]) == ["ux-grupo-resumen ux-pill ux-danger ux-pill-suave", "2 pierden plata"]
    assert _resumen([(True, 9000, 10000, 2000, 1500)])[1] == "1 pierde plata"


@CON_NODE
def test_el_resumen_muestra_lo_que_ganas_en_la_peor_y_se_pone_naranja_si_el_margen_es_bajo():
    # ganancias: 10.000 − 2.000 − 1.500 − 4.000 = 2.500 (25 %) y 10.000 − 2.000 − 1.500 − 5.500 = 1.000 (10 %): la peor deja $1.000 por unidad, bajo el 15 % de referencia
    assert _resumen([(True, 4000, 10000, 2000, 1500), (True, 5500, 10000, 2000, 1500)]) == ["ux-grupo-resumen ux-pill ux-warn ux-pill-suave", "Ganás desde $1.000 por unidad"]
    assert _resumen([(True, 4000, 10000, 2000, 1500)]) == ["ux-grupo-resumen ux-pill ux-ok ux-pill-suave", "Ganás desde $2.500 por unidad"]


@CON_NODE
def test_el_resumen_sin_datos_de_comision_no_inventa_una_ganancia():
    assert _resumen([(True, 4000, 10000, None, 1500)]) == ["ux-grupo-resumen ux-pill ux-ok ux-pill-suave", "Costo cargado"]


@CON_NODE
def test_el_resumen_de_un_grupo_todo_pausado():
    assert _resumen([(False, 0, 10000, 2000, 1500), (False, 3000, 10000, 2000, 1500)]) == ["ux-grupo-resumen ux-pill ux-neutral ux-pill-suave", "Todas pausadas"]

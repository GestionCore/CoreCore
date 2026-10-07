"""
Calidad: el mismo modelo y talle publicado varias veces (Clásica y Premium, a distintos precios) se junta en una fila con la suma y el detalle de cada una. Con datos reales se vio que
las repetidas NO son medios de pago: son publicaciones de otro tipo y otro precio, y convierten muy distinto (la Clásica, 1.792 visitas; las Premium, ~100).
"""
import os

import pytest

import calidad as c


def _pub(id_meli, tipo, precio, visitas, unidades, score=100, previas=0, titulo="Campera Jean Hombre Negra Premium L", clave=("Campera Jean Hombre Negra Premium", "L")):
    return {"id_meli": id_meli, "titulo": titulo, "thumbnail": None, "permalink": f"https://x/{id_meli}", "score": score, "tono": c._tono(score), "acciones": [], "tipo": tipo,
            "precio": float(precio), "visitas": visitas, "visitas_previas": previas, "tendencia": None, "unidades": unidades,
            "conversion": round(unidades / visitas * 100, 2) if visitas > 0 else None, "_clave": clave}


def test_la_etiqueta_distingue_el_tipo_y_el_precio():
    assert c.etiqueta_publicacion("Clásica", 65990) == "Clásica · $65.990"
    assert c.etiqueta_publicacion("Premium", None) == "Premium"
    assert c.etiqueta_publicacion(None, 73990) == "$73.990"
    assert c.etiqueta_publicacion(None, None) == ""


def test_las_publicaciones_del_mismo_modelo_y_talle_se_juntan_en_una_fila():
    pubs = [_pub("A", "Premium", 78990, 82, 2), _pub("B", "Premium", 73990, 97, 0), _pub("C", "Clásica", 65990, 1792, 21),
            _pub("D", "Clásica", 55990, 210, 0, titulo="Otro", clave=("Otro", "XL"))]
    grupos = c.agrupar_publicaciones(pubs)
    assert len(grupos) == 2
    jean = next(g for g in grupos if g["talle"] == "L")
    assert [p["id_meli"] for p in jean["publicaciones"]] == ["C", "B", "A"]            # la que más visitas recibe, primero
    assert jean["visitas"] == 82 + 97 + 1792 and jean["unidades"] == 23
    assert jean["titulo"] == pubs[2]["titulo"]


def test_la_conversion_del_grupo_se_calcula_sobre_la_suma_no_como_promedio_de_porcentajes():
    # 1 % en 1.000 visitas y 10 % en 10 visitas: el promedio simple daría 5,5 %; el real, 11 ventas sobre 1.010 visitas = 1,09 %
    grupos = c.agrupar_publicaciones([_pub("A", "Clásica", 1000, 1000, 10), _pub("B", "Premium", 1200, 10, 1)])
    assert grupos[0]["conversion"] == round(11 / 1010 * 100, 2) == 1.09


def test_cada_publicacion_de_un_grupo_se_distingue_y_la_que_esta_sola_no_lleva_etiqueta():
    grupos = c.agrupar_publicaciones([_pub("A", "Premium", 78990, 82, 2), _pub("B", "Clásica", 65990, 100, 1), _pub("S", "Premium", 50000, 5, 0, titulo="Sola", clave=("Sola", "M"))])
    doble = next(g for g in grupos if g["talle"] == "L")
    assert {p["etiqueta"] for p in doble["publicaciones"]} == {"Premium · $78.990", "Clásica · $65.990"}
    sola = next(g for g in grupos if g["talle"] == "M")
    assert sola["publicaciones"][0]["etiqueta"] == "" and sola["publicaciones"][0]["hermanas"] == 1


def test_el_puntaje_del_grupo_es_el_de_la_peor_publicacion_y_sin_datos_queda_sin_puntaje():
    grupos = c.agrupar_publicaciones([_pub("A", "Premium", 1, 10, 0, score=100), _pub("B", "Clásica", 1, 10, 0, score=72)])
    assert grupos[0]["score"] == 72 and grupos[0]["tono"] == "warn"
    sin = c.agrupar_publicaciones([_pub("A", "Premium", 1, 10, 0, score=None)])
    assert sin[0]["score"] is None and sin[0]["tono"] == "neutral"


def test_la_tendencia_es_sobre_las_visitas_juntas_y_solo_si_hay_base_suficiente():
    g = c.agrupar_publicaciones([_pub("A", "Premium", 1, 80, 0, previas=100), _pub("B", "Clásica", 1, 20, 0, previas=100)])[0]
    assert g["tendencia"] == -50                                                       # 100 visitas contra 200
    poca = c.agrupar_publicaciones([_pub("A", "Premium", 1, 5, 0, previas=10)])[0]
    assert poca["tendencia"] is None


def test_los_talles_distintos_no_se_mezclan():
    grupos = c.agrupar_publicaciones([_pub("A", "Premium", 1, 10, 0, clave=("M", "L")), _pub("B", "Premium", 1, 10, 0, clave=("M", "XL"))])
    assert len(grupos) == 2


# ── La pantalla ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
pytestmark_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL: se omiten las pruebas con la app real")


@pytestmark_db
def test_la_pantalla_muestra_una_fila_por_modelo_y_talle_con_el_detalle_de_cada_publicacion():
    import app as aplicacion
    pubs = [_pub("A", "Premium", 78990, 82, 2), _pub("B", "Clásica", 65990, 1792, 21)]
    grupos = c.agrupar_publicaciones(pubs)
    contexto = dict(total_activas=2, promedio=100, tono_promedio="ok", al_cien=2, con_dato=2, sin_revisar=0, con_mejoras=[], top_acciones=[], total_acciones=0, total_visitas=1874,
                    tendencia_visitas=None, conversion=1.23, total_unidades=23, mas_visitadas=[pubs[1]], perdiendo_visitas=[], visitas_sin_ventas=[], items=pubs, grupos=grupos)
    with aplicacion.app.test_request_context("/"):
        html = aplicacion.render_template("calidad.html", active_nav="calidad", **contexto)
    assert "2 publicaciones · ver el detalle" in html and html.count('class="ux-subfila"') == 2
    assert "Clásica · $65.990" in html and "Premium · $78.990" in html
    assert "cada una convierte distinto" in html
    assert "1 modelo y talle" in html or "1 modelo y variante" in html
    # el desplegable lo maneja la pieza compartida, no un script de esta pantalla
    assert "ux-toggle-variantes" in html and "alternarDetalle" not in html

"""
«Reclamos y devoluciones» dentro de Día a día (reclamos_dia.py, templates/_dia_reclamos.html).

Pedido del dueño: «mirar reclamos hoy no se entiende». Antes solo había contadores («2 reclamos»): no decían cuál era, por qué, si afectaba la reputación ni qué hacer. Ahora cada caso abierto
es una tarjeta, con lo más urgente primero. Las pruebas usan casos armados a mano (no capturas del resultado) y verifican que NUNCA se invente un dato: lo que Mercado Libre no informó, se dice.
"""
import os
import re
from datetime import date, datetime

import pytest

import reclamos_dia

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")
HOY = date(2026, 10, 22)


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


def _caso(id_reclamo, tipo="claim", estado="claim", afecta="affected", dias=3, retenido=0, titulo="Campera de jean", motivo="Llegó dañado", orden="2000001"):
    return {"id_reclamo": id_reclamo, "id_orden": orden, "tipo": tipo, "motivo": motivo, "estado": estado, "monto_retenido": retenido,
            "fecha": datetime(2026, 10, 22 - dias, 9, 0), "afecta_reputacion": afecta, "titulo": titulo}


def test_lo_que_afecta_la_reputacion_va_primero_y_en_mediacion_antes_que_el_resto():
    casos = [
        _caso("a", tipo="return", estado="claim", afecta=None, dias=9),                      # devolución: no afecta por sí sola
        _caso("b", estado="claim", afecta="not_affected", dias=5),                           # reclamo que no afecta
        _caso("c", estado="claim", afecta="affected", dias=2),                               # afecta
        _caso("d", estado="mediation", afecta="affected", dias=1),                           # afecta y en mediación: lo primero
        _caso("e", estado="mediation", afecta="not_affected", dias=7),                       # en mediación pero no afecta
    ]
    assert [t["id"] for t in reclamos_dia.armar(casos, HOY)] == ["d", "c", "e", "b", "a"]


def test_a_igual_urgencia_va_primero_el_mas_viejo():
    casos = [_caso("nuevo", dias=1), _caso("viejo", dias=12), _caso("medio", dias=5)]
    assert [t["id"] for t in reclamos_dia.armar(casos, HOY)] == ["viejo", "medio", "nuevo"]


def test_cada_caso_dice_cuanto_hace_que_esta_abierto():
    t = {x["id"]: x["desde"] for x in reclamos_dia.armar([_caso("hoy", dias=0), _caso("ayer", dias=1), _caso("tres", dias=3)], HOY)}
    assert t == {"hoy": "hoy", "ayer": "ayer", "tres": "hace 3 días"}


def test_si_mercado_libre_no_informo_si_afecta_la_reputacion_se_dice_y_cuenta_como_posible():
    (t,) = reclamos_dia.armar([_caso("x", afecta=None)], HOY)
    assert t["impacto"] == "Mercado Libre todavía no informó si afecta tu reputación" and t["tono"] == "warn"
    assert reclamos_dia.resumen([t])["afectan"] == 1                                         # igual que el ticker y Salud de cuenta: ante la duda, cuenta
    (t,) = reclamos_dia.armar([_caso("y", afecta="not_affected")], HOY)
    assert t["impacto"] == "No afecta tu reputación" and t["tono"] == "neutral"
    (t,) = reclamos_dia.armar([_caso("z", afecta="affected")], HOY)
    assert t["impacto"] == "Afecta tu reputación" and t["tono"] == "danger"


def test_una_devolucion_o_una_cancelacion_no_se_presenta_como_un_reclamo_grave():
    for tipo, texto in (("return", "Devolución o cambio"), ("cancelacion", "Cancelación")):
        (t,) = reclamos_dia.armar([_caso("x", tipo=tipo, afecta="affected")], HOY)              # aunque el dato diga «affected», no es un reclamo
        assert t["tipo_texto"] == texto and t["impacto"] == "No afecta tu reputación por sí sola" and t["tono"] == "neutral"
    (t,) = reclamos_dia.armar([_caso("x", tipo="return", estado="claim")], HOY)
    assert t["estado_texto"] == "Abierto"                                                      # la etapa interna «claim» no se lee como «Reclamo activo» en una devolución


def test_lo_que_se_le_dice_a_la_persona_que_haga_depende_del_caso_y_no_promete_nada():
    (mediacion,) = reclamos_dia.armar([_caso("m", estado="mediation")], HOY)
    assert mediacion["estado_texto"] == "En mediación con Mercado Libre" and "respondé o cargá lo que te pidan" in mediacion["que_hacer"]
    (abierto,) = reclamos_dia.armar([_caso("a", estado="claim")], HOY)
    assert "cuanto antes" in abierto["que_hacer"]
    (devolucion,) = reclamos_dia.armar([_caso("d", tipo="return")], HOY)
    assert "revisalo y confirmalo" in devolucion["que_hacer"]
    (cancelacion,) = reclamos_dia.armar([_caso("c", tipo="cancelacion")], HOY)
    assert "No tenés que hacer nada" in cancelacion["que_hacer"]
    for t in (mediacion, abierto, devolucion, cancelacion):
        assert not re.search(r"garantiz|seguro que|siempre|nunca|perd[eé]r[aá]s", t["que_hacer"], re.I)


def test_sin_producto_ni_motivo_se_dice_en_vez_de_dejar_el_hueco():
    (t,) = reclamos_dia.armar([_caso("x", titulo=None, motivo=None, orden="2000099")], HOY)
    assert t["titulo"] == "Venta 2000099" and t["motivo"] == "Mercado Libre no informó el motivo"
    assert t["link"] == "https://www.mercadolibre.com.ar/ventas/2000099/detalle"
    (t,) = reclamos_dia.armar([_caso("y", orden="")], HOY)
    assert t["link"] is None                                                                  # sin orden no hay a dónde llevar: no se arma un link roto


def test_la_plata_retenida_solo_aparece_si_hay():
    tarjetas = {t["id"]: t for t in reclamos_dia.armar([_caso("a", retenido=0), _caso("b", retenido=53190.5)], HOY)}
    assert tarjetas["a"]["retenido_texto"] is None and tarjetas["b"]["retenido_texto"] == "53.190"
    r = reclamos_dia.resumen(list(tarjetas.values()))
    assert r["retenido"] == 53190.5 and r["retenido_texto"] == "53.190"


def test_la_frase_de_arriba_resume_sin_exagerar():
    assert reclamos_dia.resumen([])["frase"] == "No tenés reclamos ni devoluciones abiertos."
    uno = reclamos_dia.resumen(reclamos_dia.armar([_caso("a", afecta="affected")], HOY))
    assert uno["frase"] == "1 reclamo puede afectar tu reputación: empezá por ese."
    varios = reclamos_dia.resumen(reclamos_dia.armar([_caso("a"), _caso("b"), _caso("c", afecta="not_affected")], HOY))
    assert varios["frase"] == "2 reclamos pueden afectar tu reputación: empezá por los de arriba." and varios["abiertos"] == 3
    ninguno = reclamos_dia.resumen(reclamos_dia.armar([_caso("a", afecta="not_affected"), _caso("b", tipo="return")], HOY))
    assert ninguno["frase"] == "Tenés 2 casos abiertos, ninguno afecta tu reputación."


def test_los_textos_de_mercado_libre_se_escapan_en_la_pantalla():
    import app as aplicacion
    from flask import render_template
    casos = reclamos_dia.armar([_caso("x", titulo="<script>alert(1)</script> Campera", motivo="<img src=x onerror=alert(2)>")], HOY)
    with aplicacion.app.test_request_context("/dia"):
        html = render_template("_dia_reclamos.html", reclamos=casos, reclamos_resumen=reclamos_dia.resumen(casos))
    assert "<script>alert(1)" not in html and "<img src=x" not in html and "&lt;script&gt;" in html


def test_la_pantalla_dibuja_tarjetas_resumen_y_el_vacio():
    import app as aplicacion
    from flask import render_template
    casos = reclamos_dia.armar([_caso("a", afecta="affected", estado="mediation", retenido=1000), _caso("b", tipo="return")], HOY)
    with aplicacion.app.test_request_context("/dia"):
        lleno = render_template("_dia_reclamos.html", reclamos=casos, reclamos_resumen=reclamos_dia.resumen(casos))
        vacio = render_template("_dia_reclamos.html", reclamos=[], reclamos_resumen=reclamos_dia.resumen([]))
    assert lleno.count('class="rc-tarjeta') == 2 and "Qué hacer:" in lleno and "Abrir en Mercado Libre" in lleno and "$1.000 retenidos" in lleno
    assert 'rc-danger' in lleno and "Afecta tu reputación" in lleno
    assert lleno.count("btn-primary") == 0                                    # la pantalla ya tiene su botón principal
    assert "No tenés reclamos ni devoluciones abiertos" in vacio and "rc-tarjeta" not in vacio


# ── Cableado ────────────────────────────────────────────────────────────────────
def test_reclamos_es_una_parte_mas_de_dia_a_dia_con_su_pestana_y_su_resumen():
    import nav_config
    paginas = nav_config.GRUPOS_NAV["dia"]["paginas"]
    assert [p["label"] for p in paginas] == ["Despacho", "Preguntas", "Reclamos", "Pendientes", "Reputación"]
    assert [p for p in paginas if p["label"] == "Reclamos"][0]["ancla"] == "reclamos"
    dia = _leer("templates", "dia.html")
    assert '<section class="dia-seccion" id="reclamos"' in dia and '{% include "_dia_reclamos.html" %}' in dia and 'href="#reclamos"' in dia
    assert dia.index('id="preguntas"') < dia.index('id="reclamos"') < dia.index('id="pendientes"')       # el orden de la pantalla es el de las pestañas
    app_py = _leer("app.py")
    assert '("reclamos", _contexto_reclamos)' in app_py
    import asistente
    assert "reclamos" in asistente.GUIA_DE_PANTALLAS


@CON_BASE
def test_la_consulta_corre_contra_la_base_real_y_solo_trae_lo_abierto():
    import db
    with db.conexion_admin() as conexion:
        cur = conexion.cursor()
        cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
        fila = cur.fetchone()
        if not fila:
            pytest.skip("Hace falta al menos una cuenta en la base")
        filas = reclamos_dia.listar_abiertos(cur, fila[0])
    assert all(f["estado"] not in ("closed", "resolved") for f in filas)
    tarjetas = reclamos_dia.armar(filas, HOY)
    assert len(tarjetas) == len(filas) and all(t["tipo"] in reclamos_dia.TIPOS for t in tarjetas)

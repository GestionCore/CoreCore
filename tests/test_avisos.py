"""Avisos de la campana: qué hay para mirar ya, en castellano, con lo más urgente primero. Sin base."""
import os
import re

import dashboard as d


def test_sin_nada_para_mirar_no_hay_avisos():
    assert d.armar_avisos(0, 0, 0, 0) == {"total": 0, "items": []}


def test_cada_aviso_dice_el_numero_en_singular_o_plural():
    a = d.armar_avisos(preguntas=1, reclamos=1, devoluciones=1, sin_stock=1)
    assert [i["texto"] for i in a["items"]] == ["1 reclamo que afecta tu reputación", "1 pregunta sin responder", "1 publicación activa sin stock", "1 devolución por gestionar"]
    b = d.armar_avisos(preguntas=3, reclamos=2, devoluciones=5, sin_stock=4)
    assert [i["texto"] for i in b["items"]] == ["2 reclamos que afectan tu reputación", "3 preguntas sin responder", "4 publicaciones activas sin stock", "5 devoluciones por gestionar"]


def test_lo_mas_urgente_va_primero_y_el_total_suma_las_cantidades():
    a = d.armar_avisos(preguntas=2, reclamos=1, devoluciones=0, sin_stock=3)
    assert [i["clave"] for i in a["items"]] == ["reclamos", "preguntas", "sin_stock"]          # sin devoluciones: no aparece
    assert a["total"] == 6
    assert a["items"][0]["tono"] == "danger" and a["items"][1]["tono"] == "warn"


def test_cada_aviso_lleva_su_destino_y_su_icono():
    a = d.armar_avisos(1, 1, 1, 1)
    for i in a["items"]:
        assert i["href"].startswith("/") and i["icono"] and i["cantidad"] == 1


def test_un_numero_negativo_o_vacio_no_genera_aviso():
    assert d.armar_avisos(None, 0, "", 0)["items"] == []


class _Cursor:
    """Doble de cursor: anota las consultas y contesta un número por cada una."""

    def __init__(self, respuestas):
        self.sql, self._respuestas = [], list(respuestas)

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return (self._respuestas.pop(0),)


def test_cuenta_preguntas_pendientes_y_publicaciones_activas_sin_stock():
    c = _Cursor([4, 2])
    assert d.contar_preguntas_y_sin_stock(c) == (4, 2)
    assert "preguntas_pendientes" in c.sql[0] and "'pendiente'" in c.sql[0]
    # sin stock = activa y sin una sola unidad (propia + FULL); una pausada o cerrada sin stock no es un aviso
    assert "estado = 'active'" in c.sql[1] and "stock_propio" in c.sql[1] and "stock_full" in c.sql[1]


def test_un_conteo_vacio_cuenta_cero():
    assert d.contar_preguntas_y_sin_stock(_Cursor([None, None])) == (0, 0)


def test_el_ticker_entrega_los_avisos_listos_para_la_campana():
    fuente = open(d.__file__, encoding="utf-8").read()
    assert '"avisos": armar_avisos(' in fuente


# ── La campana (HTML + JS): el JS busca estos ids; si uno falta, la campana no se pinta y nadie lo nota ──
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(*ruta):
    return open(os.path.join(RAIZ, *ruta), encoding="utf-8").read()


def test_la_barra_superior_trae_la_campana_con_los_ids_que_usa_el_js():
    base, js = _leer("templates", "base.html"), _leer("static", "js", "global.js")
    usados = set(re.findall(r"getElementById\('((?:btn-avisos|panel-avisos|avisos-[a-z]+))'\)", js))
    assert usados == {"btn-avisos", "panel-avisos", "avisos-cuenta", "avisos-lista"}
    for i in usados:
        assert f'id="{i}"' in base, f"base.html no tiene #{i}"
    assert 'aria-controls="panel-avisos"' in base and 'aria-expanded="false"' in base       # accesible: el lector de pantalla sabe qué abre y si está abierto


def test_la_campana_se_inicializa_al_arrancar_y_el_ticker_la_alimenta():
    js = _leer("static", "js", "global.js")
    arranque = js[js.index("// ---------- Arranque global ----------"):]
    assert "inicializarAvisos();" in arranque
    ticker = js[js.index("async function actualizarTicker()"):js.index("// ---------- Tooltips ricos")]
    assert "_avisos.derivados = " in ticker and "_pintarAvisos()" in ticker


def test_el_texto_externo_de_los_avisos_no_se_inyecta_como_html():
    """Los títulos y mensajes de las alertas guardadas vienen de la base: van por textContent, nunca por innerHTML."""
    js = _leer("static", "js", "global.js")
    fila = js[js.index("function _filaAviso"):js.index("function _pintarAvisos")]
    assert "textContent = texto" in fila and "textContent = detalle" in fila
    assert "innerHTML" in fila and "${icono}" in fila          # lo único que entra por innerHTML es el nombre de un ícono nuestro
    assert "${texto}" not in fila and "${detalle}" not in fila

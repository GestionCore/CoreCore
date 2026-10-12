"""
Monotributo (monotributo.py): categoría que corresponde a la facturación real de 12 meses, comparación con la declarada y avisos. Es un consejo FISCAL: tiene que avisar cuando corresponde (y no inventar avisos).
La fecha de «hoy» está fija en estas pruebas (15/10/2026) y la base simulada; los topes salen de la tabla vigente del módulo.
"""
from datetime import datetime

import pytest

import monotributo
from utils import ARGENTINA

HOY = datetime(2026, 10, 15, 12, 0, tzinfo=ARGENTINA)
TOPE = {e["categoria"]: e["tope_anual"] for e in monotributo.ESCALAS}


class _Fecha(datetime):
    @classmethod
    def now(cls, tz=None):
        return HOY if tz is not None else HOY.replace(tzinfo=None)


class _Cursor:
    def __init__(self, resultados):
        self.resultados = list(resultados)

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self.resultados.pop(0)


class _Conexion:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cursor


def _evaluar(monkeypatch, f12, f3, f3_ant, precio_max=0, declarada=None):
    """Orden de las consultas del módulo: 12 meses, últimos 3, 3 anteriores, precio máximo, categoría declarada."""
    cursor = _Cursor([(f12,), (f3,), (f3_ant,), (precio_max,), (declarada,) if declarada is not None else None])
    monkeypatch.setattr(monotributo.db, "conexion_usuario", lambda u, c: _Conexion(cursor))
    monkeypatch.setattr(monotributo, "datetime", _Fecha)
    return monotributo.evaluar_categoria(1, 7)


def _tipos(r):
    return [a["tipo"] for a in r["alertas"]]


# ── Qué categoría corresponde ───────────────────────────────────────────────────────────────────────────────────────────────

def test_la_categoria_es_la_primera_cuyo_tope_alcanza_y_el_tope_incluye_su_valor_exacto():
    assert monotributo._categoria_para_facturacion(0)["categoria"] == "A"
    assert monotributo._categoria_para_facturacion(TOPE["A"])["categoria"] == "A"
    assert monotributo._categoria_para_facturacion(TOPE["A"] + 0.01)["categoria"] == "B"
    assert monotributo._categoria_para_facturacion(TOPE["H"])["categoria"] == "H"
    assert monotributo._categoria_para_facturacion(TOPE["H"] + 0.01) is None                      # pasó la H: ya no es monotributo


def test_la_tabla_esta_ordenada_y_crece():
    topes = [e["tope_anual"] for e in monotributo.ESCALAS]
    cuotas = [e["cuota_mensual"] for e in monotributo.ESCALAS]
    assert topes == sorted(topes) and cuotas == sorted(cuotas) and [e["categoria"] for e in monotributo.ESCALAS] == list("ABCDEFGH")


@pytest.mark.parametrize("hoy, esperada", [
    (datetime(2026, 10, 15), datetime(2027, 1, 1)),
    (datetime(2026, 1, 1), datetime(2026, 7, 1)),                 # justo el día de la ventana: la próxima es la siguiente
    (datetime(2026, 1, 2), datetime(2026, 7, 1)),
    (datetime(2026, 7, 1, 0, 0), datetime(2027, 1, 1)),
    (datetime(2026, 12, 31), datetime(2027, 1, 1)),
])
def test_proxima_ventana_de_recategorizacion(hoy, esperada):
    assert monotributo._proxima_ventana_recategorizacion(hoy) == esperada


# ── Avisos ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_sin_categoria_declarada_solo_informa_la_que_le_corresponde(monkeypatch):
    r = _evaluar(monkeypatch, 15_000_000, 4_000_000, 3_000_000)
    assert r["categoria_real"] == "B" and r["categoria_declarada"] is None and r["alertas"] == []
    assert r["cuota_mensual_declarada"] is None and r["tope_categoria_declarada"] is None and r["vigente_desde"] == monotributo.ESCALAS_VIGENTES_DESDE


def test_si_factura_mas_de_lo_que_declara_se_avisa_como_urgente(monkeypatch):
    r = _evaluar(monkeypatch, 20_000_000, 5_000_000, 5_000_000, declarada="B")                  # corresponde C (hasta 24,7 M) y declaró B (hasta 17,6 M)
    assert r["categoria_real"] == "C" and _tipos(r) == ["urgente"]
    assert "Categoría C" in r["alertas"][0]["texto"] and "declarada la B" in r["alertas"][0]["texto"]


def test_si_factura_muy_por_debajo_de_su_categoria_se_ofrece_bajar(monkeypatch):
    r = _evaluar(monkeypatch, 10_000_000, 2_500_000, 2_500_000, declarada="D")                  # D llega a 30,6 M: usa el 32,6 %; le alcanzaría la A
    assert r["categoria_real"] == "A" and _tipos(r) == ["oportunidad"] and "32.6%" in r["alertas"][0]["texto"]


def test_por_debajo_de_su_categoria_pero_usando_mas_del_60_no_se_dice_nada(monkeypatch):
    r = _evaluar(monkeypatch, 20_000_000, 5_000_000, 5_000_000, declarada="D")                  # corresponde C, declaró D, usa el 65,3 % de D
    assert r["categoria_real"] == "C" and r["alertas"] == []


def test_cerca_del_techo_de_su_categoria_se_avisa_que_falta_poco(monkeypatch):
    # Declaró C (tope 24,67 M) y corresponde C: factura el 90,0 % del techo. Es el aviso que más importa y el que antes nunca salía.
    r = _evaluar(monkeypatch, 0.90 * TOPE["C"], 5_000_000, 5_000_000, declarada="C")
    assert r["categoria_real"] == "C" and _tipos(r) == ["importante"]
    assert "90.0%" in r["alertas"][0]["texto"] and "(C)" in r["alertas"][0]["texto"] and "Falta poco" in r["alertas"][0]["texto"]


def test_justo_en_el_85_por_ciento_se_avisa_y_apenas_debajo_no(monkeypatch):
    assert _tipos(_evaluar(monkeypatch, 0.85 * TOPE["C"], 1, 1, declarada="C")) == ["importante"]
    assert _tipos(_evaluar(monkeypatch, 0.849 * TOPE["C"], 1, 1, declarada="C")) == []


def test_pasar_el_techo_de_todas_las_categorias_avisa_una_sola_vez_y_no_dice_que_falta_poco(monkeypatch):
    r = _evaluar(monkeypatch, TOPE["H"] * 1.05, 20_000_000, 20_000_000, declarada="H")
    assert r["categoria_real"] is None and _tipos(r) == ["urgente"]
    assert "Responsable Inscripto" in r["alertas"][0]["texto"] and "Falta poco" not in r["alertas"][0]["texto"]


def test_un_articulo_mas_caro_que_el_maximo_permitido_avisa_y_sugiere_confirmar_con_el_contador(monkeypatch):
    r = _evaluar(monkeypatch, 5_000_000, 1_000_000, 1_000_000, precio_max=monotributo.PRECIO_UNITARIO_MAXIMO + 1, declarada="A")
    assert _tipos(r) == ["urgente"] and "contador" in r["alertas"][0]["texto"]
    assert _tipos(_evaluar(monkeypatch, 5_000_000, 1_000_000, 1_000_000, precio_max=monotributo.PRECIO_UNITARIO_MAXIMO, declarada="A")) == []     # justo el máximo: permitido


# ── Proyección con el ritmo propio ──────────────────────────────────────────────────────────────────────────────────────────

def test_proyecta_cuando_al_ritmo_actual_cruza_antes_de_la_proxima_ventana(monkeypatch):
    # Declaró C; 12 meses = tope − 1.500.000. Los últimos 3 meses (6 M) crecieron un 50 % sobre los 3 anteriores (4 M):
    # crecimiento = (6 M ÷ 3) × 0,5 = 1 M por mes → 1,5 meses para llegar al techo; la próxima ventana (1/1/2027) está a 78 días = 2,6 meses.
    r = _evaluar(monkeypatch, TOPE["C"] - 1_500_000, 6_000_000, 4_000_000, declarada="C")
    assert r["variacion_pct_propia"] == 50.0 and r["meses_para_cruzar"] == 1.5
    proyeccion = [a for a in r["alertas"] if a["tipo"] == "proyeccion"]
    assert len(proyeccion) == 1 and "unos 1.5 meses" in proyeccion[0]["texto"] and "enero 2027" in proyeccion[0]["texto"]


def test_no_proyecta_si_cruza_despues_de_la_proxima_ventana_o_si_no_crece(monkeypatch):
    # margen 4,67 M ÷ 1 M por mes = 4,7 meses: pasada la ventana de enero (2,6 meses), se recategoriza antes de cruzar
    r = _evaluar(monkeypatch, 20_000_000, 6_000_000, 4_000_000, declarada="C")
    assert r["meses_para_cruzar"] == 4.7 and "proyeccion" not in _tipos(r)
    cae = _evaluar(monkeypatch, 20_000_000, 3_000_000, 4_000_000, declarada="C")                  # las ventas vienen cayendo: no hay proyección
    assert cae["variacion_pct_propia"] == -25.0 and cae["meses_para_cruzar"] is None
    sin_base = _evaluar(monkeypatch, 20_000_000, 3_000_000, 0, declarada="C")                     # sin ventas en los 3 meses anteriores no hay con qué comparar
    assert sin_base["variacion_pct_propia"] is None and sin_base["meses_para_cruzar"] is None


def test_la_proyeccion_dice_un_mes_cuando_es_exactamente_uno(monkeypatch):
    r = _evaluar(monkeypatch, TOPE["C"] - 1_000_000, 6_000_000, 4_000_000, declarada="C")
    assert r["meses_para_cruzar"] == 1.0
    assert any("en un mes" in a["texto"] for a in r["alertas"] if a["tipo"] == "proyeccion")


# ── Guardar la categoría declarada ──────────────────────────────────────────────────────────────────────────────────────────

def test_solo_se_guardan_categorias_que_existen(monkeypatch):
    guardados = []

    class _C:
        def execute(self, sql, params=None):
            guardados.append(params)

    monkeypatch.setattr(monotributo.db, "conexion_usuario", lambda u, c: _Conexion(_C()))
    assert monotributo.guardar_categoria_declarada(1, 7, "Z") is False and guardados == []
    assert monotributo.guardar_categoria_declarada(1, 7, "C") is True and guardados == [("C", 7)]
    assert monotributo.guardar_categoria_declarada(1, 7, "") is True and guardados[-1] == (None, 7)       # vaciarla (no sé cuál tengo) es válido

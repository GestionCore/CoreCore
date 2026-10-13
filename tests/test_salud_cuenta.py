"""
Score de salud de la cuenta (salud_cuenta.calcular_score_salud): 100 menos descuentos con tope por tipo. Lo muestran la campana, el ticker y Día a día.
Cada descuento y su tope, el recorte entre 0 y 100, las etiquetas por tramo y los textos en singular/plural. La base está simulada.
"""
import pytest

import salud_cuenta


class _Cursor:
    """Responde por el texto del SQL; guarda las consultas hechas."""

    def __init__(self, reclamos=0, stocks=(), ventas_semana=0.0, ventas_anterior=0.0, preguntas_viejas=0):
        self.reclamos, self.stocks, self.preguntas_viejas = reclamos, list(stocks), preguntas_viejas
        self.ventas = [ventas_semana, ventas_anterior]
        self.consultas, self.ultimo = [], None

    def execute(self, sql, params=None):
        self.ultimo = " ".join(sql.split())
        self.consultas.append(self.ultimo)

    def fetchone(self):
        if "incidencias_posventa" in self.ultimo:
            return (self.reclamos,)
        if "FROM ventas" in self.ultimo:
            return (self.ventas.pop(0),)
        return (self.preguntas_viejas,)

    def fetchall(self):
        return [(s,) for s in self.stocks]


@pytest.fixture
def curva(monkeypatch):
    """Cuántas variantes clave sin stock devuelve el análisis de stock (por defecto, ninguna)."""
    def fijar(modelos):
        monkeypatch.setattr(salud_cuenta.analisis_stock, "evaluar_cobertura_variantes", lambda cursor: [object()] * modelos)
    fijar(0)
    return fijar


def _score(**kw):
    return salud_cuenta.calcular_score_salud(_Cursor(**kw))


def test_una_cuenta_sin_problemas_tiene_100_y_ningun_detalle(curva):
    assert _score() == {"score": 100, "etiqueta": "Muy bien", "detalle": []}


@pytest.mark.parametrize("reclamos, resta", [(1, 15), (2, 30), (3, 45), (4, 45), (10, 45)])
def test_cada_reclamo_activo_resta_15_con_tope_de_45(curva, reclamos, resta):
    r = _score(reclamos=reclamos)
    assert r["score"] == 100 - resta and r["detalle"][0].startswith(f"-{resta} por {reclamos} reclamo")


def test_solo_cuentan_los_reclamos_abiertos_que_afectan_la_reputacion(curva):
    """Una devolución o un «no lo quiero» en mediación que Mercado Libre marca «no afecta» NO restan (antes 4 de esos restaban 45 puntos)."""
    cursor = _Cursor()
    salud_cuenta.calcular_score_salud(cursor)
    sql = cursor.consultas[0]
    assert "tipo = 'claim'" in sql and "estado NOT IN ('closed', 'resolved')" in sql and salud_cuenta.SQL_RECLAMO_AFECTA in sql


@pytest.mark.parametrize("sin_stock, resta", [(1, 4), (3, 12), (5, 20), (9, 20)])
def test_cada_talle_sin_stock_resta_4_con_tope_de_20(curva, sin_stock, resta):
    r = _score(stocks=[0] * sin_stock + [10, 10])
    assert r["score"] == 100 - resta and f"-{resta} por " in r["detalle"][0]


@pytest.mark.parametrize("bajos, resta", [(1, 2), (4, 8), (5, 10), (8, 10)])
def test_cada_talle_con_stock_de_1_o_2_resta_2_con_tope_de_10(curva, bajos, resta):
    r = _score(stocks=[1] * bajos + [3, 50])                                      # el stock de 3 en adelante no cuenta
    assert r["score"] == 100 - resta


def test_los_textos_van_en_singular_y_plural_y_sin_parentesis(curva):
    assert _score(stocks=[0, 1])["detalle"] == ["-4 por 1 talle sin stock dentro de publicaciones activas", "-2 por 1 talle con stock muy bajo (1-2 u.)"]
    assert _score(stocks=[0, 0, 1, 1, 2])["detalle"] == ["-8 por 2 talles sin stock dentro de publicaciones activas", "-6 por 3 talles con stock muy bajo (1-2 u.)"]
    curva(1)
    todo = " ".join(_score(reclamos=1, stocks=[0, 1], preguntas_viejas=1)["detalle"])
    assert "(s)" not in todo and "(es)" not in todo


@pytest.mark.parametrize("modelos, resta", [(1, 10), (2, 20), (5, 20)])
def test_cada_variante_clave_sin_stock_resta_10_con_tope_de_20(curva, modelos, resta):
    curva(modelos)
    r = _score()
    assert r["score"] == 100 - resta
    assert "variante" in r["detalle"][0] and "30 %" in r["detalle"][0] and "talles" not in r["detalle"][0]      # ya no habla de curva de talles: sirve para cualquier rubro


def test_si_la_cobertura_de_variantes_falla_el_score_se_calcula_igual(monkeypatch):
    def roto(cursor):
        raise RuntimeError("no se pudo evaluar")
    monkeypatch.setattr(salud_cuenta.analisis_stock, "evaluar_cobertura_variantes", roto)
    assert salud_cuenta.calcular_score_salud(_Cursor())["score"] == 100


@pytest.mark.parametrize("semana, anterior, descuenta", [
    (80, 100, True),            # -20 %: justo el límite, descuenta
    (79, 100, True),
    (81, 100, False),           # -19 %: no
    (200, 100, False),          # crece
    (0, 100, True),             # se cayó a cero
    (50, 0, False),             # no hay con qué comparar: nunca se descuenta
])
def test_una_caida_de_facturacion_de_20_por_ciento_o_mas_resta_15(curva, semana, anterior, descuenta):
    r = _score(ventas_semana=float(semana), ventas_anterior=float(anterior))
    assert r["score"] == (85 if descuenta else 100)
    if descuenta:
        assert r["detalle"][0].startswith("-15 por caída de facturación de ") and r["detalle"][0].endswith("% vs. la semana anterior")


def test_las_preguntas_sin_responder_hace_mas_de_un_dia_restan_10_aunque_sean_muchas(curva):
    assert _score(preguntas_viejas=1)["score"] == 90 and _score(preguntas_viejas=40)["score"] == 90
    assert _score(preguntas_viejas=1)["detalle"] == ["-10 por 1 pregunta sin responder hace más de 24 h"]


def test_todo_junto_nunca_baja_de_cero(curva):
    curva(5)
    r = _score(reclamos=9, stocks=[0] * 9 + [1] * 9, ventas_semana=0.0, ventas_anterior=100.0, preguntas_viejas=3)       # 45 + 20 + 10 + 20 + 15 + 10 = 120
    assert r["score"] == 0 and r["etiqueta"] == "Crítico" and len(r["detalle"]) == 6


def test_las_etiquetas_por_tramo_en_sus_bordes(curva):
    # 100 y 85 → Muy bien; 84 a 65 → Bien; 64 a 45 → Atención; menos de 45 → Crítico
    assert _score()["etiqueta"] == "Muy bien"
    assert (_score(reclamos=1)["score"], _score(reclamos=1)["etiqueta"]) == (85, "Muy bien")
    assert (_score(reclamos=1, preguntas_viejas=1)["score"], _score(reclamos=1, preguntas_viejas=1)["etiqueta"]) == (75, "Bien")
    assert (_score(reclamos=3, stocks=[0] * 4, preguntas_viejas=1)["score"], _score(reclamos=3, stocks=[0] * 4, preguntas_viejas=1)["etiqueta"]) == (29, "Crítico")
    assert (_score(reclamos=2, stocks=[0] * 5)["score"], _score(reclamos=2, stocks=[0] * 5)["etiqueta"]) == (50, "Atención")           # 100 − 30 − 20
    assert (_score(reclamos=2, stocks=[0] * 5, preguntas_viejas=1)["score"], _score(reclamos=2, stocks=[0] * 5, preguntas_viejas=1)["etiqueta"]) == (40, "Crítico")
    assert (_score(reclamos=1, stocks=[0] * 3, preguntas_viejas=1)["score"], _score(reclamos=1, stocks=[0] * 3, preguntas_viejas=1)["etiqueta"]) == (63, "Atención")
    assert (_score(reclamos=1, stocks=[0] * 2)["score"], _score(reclamos=1, stocks=[0] * 2)["etiqueta"]) == (77, "Bien")

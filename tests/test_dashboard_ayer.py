"""Por la mañana el Dashboard compara con AYER A ESTA MISMA HORA (contra el promedio del día entero cualquier mañana parece floja)."""
from datetime import datetime, timedelta, timezone

import dashboard as d

ARG = timezone(timedelta(hours=-3))
AHORA = datetime(2026, 10, 2, 11, 30, tzinfo=ARG)           # viernes 11:30


def _venta(momento, ganancia):
    return {"momento": momento, "raw": {"ganancia_neta": ganancia}}


def test_suma_solo_lo_de_ayer_hasta_esta_hora():
    ventas = [
        _venta("2026-10-01T00:05", 1000.0),      # ayer, madrugada: entra
        _venta("2026-10-01T11:30", 500.0),       # ayer, justo a esta hora: entra
        _venta("2026-10-01T11:31", 7000.0),      # ayer, un minuto después: no
        _venta("2026-10-01T18:00", 9000.0),      # ayer, tarde: no
        _venta("2026-10-02T09:00", 300.0),       # hoy: no
        _venta("2026-09-30T10:00", 4000.0),      # anteayer: no
    ]
    assert d.ganancia_de_ayer_hasta_la_hora(ventas, AHORA) == (1500.0, 2)


def test_una_perdida_de_ayer_resta():
    assert d.ganancia_de_ayer_hasta_la_hora([_venta("2026-10-01T09:00", 800.0), _venta("2026-10-01T10:00", -300.0)], AHORA) == (500.0, 2)


def test_sin_ventas_o_sin_momento_da_cero():
    assert d.ganancia_de_ayer_hasta_la_hora([], AHORA) == (0.0, 0)
    assert d.ganancia_de_ayer_hasta_la_hora([_venta(None, 100.0), {"raw": {"ganancia_neta": 5}}], AHORA) == (0.0, 0)


# ── Top de modelos: siempre por modelo, nunca por talle ───────────────────────────────────────────────────────────────────────

def _fila(titulo, id_meli, unidades, facturado, miniatura="foto.jpg", existe=True):
    return (titulo, id_meli, unidades, facturado, miniatura, existe)


def test_los_talles_de_un_modelo_se_suman_en_un_solo_puesto():
    filas = [
        _fila("Campera De Jean Hombre Negra Talle L", "MLA1", 59, 3000000),
        _fila("Campera De Jean Hombre Negra Talle XL", "MLA2", 49, 2600000),
        _fila("Campera De Jean Hombre Negra Talle M", "MLA3", 44, 2400000),
        _fila("Medias Corta Hombre Pack", "MLA9", 2, 15000),
    ]
    top = d.top_modelos(filas)
    assert [m["nombre"] for m in top] == ["Campera De Jean Hombre Negra", "Medias Corta Hombre Pack"]
    assert top[0]["unidades"] == 152 and top[0]["publicaciones"] == 3 and top[0]["facturado"] == 8000000
    assert top[0]["id_meli"] == "MLA1"                      # la publicación que más facturó del modelo abre el panel
    assert top[0]["pct"] == 100 and top[1]["pct"] == 0


def test_pct_es_del_total_de_todos_los_modelos_no_solo_del_top():
    filas = [_fila(f"Modelo {chr(65 + i)} Premium", f"MLA{i}", 1, 100) for i in range(8)]
    top = d.top_modelos(filas, maximo=5)
    assert len(top) == 5 and all(m["pct"] == 12 for m in top)      # 100 de 800 = 12,5 %: no 20 % como saldría repartiendo solo entre los 5


def test_sin_titulo_y_publicacion_borrada():
    top = d.top_modelos([_fila("", None, 1, 500, None, False), _fila("Remera Lisa", "MLA5", 3, 900, None, False)])
    assert top[0]["nombre"] == "Remera Lisa" and top[0]["id_meli"] is None          # no existe en la base: no se ofrece abrir el panel
    assert top[1]["nombre"] == "Sin nombre"

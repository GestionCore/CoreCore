import chat_ia
from utils import hoy_argentina


def test_los_talles_se_suman_en_un_solo_modelo_y_se_ordena_por_facturado():
    filas = [
        ("Campera De Jean Hombre Negra XL", 3, 30000),
        ("Campera De Jean Hombre Negra L", 2, 20000),
        ("Remera Lisa Blanca M", 10, 25000),
        (None, 1, 500),
    ]
    top = chat_ia._consolidar_por_modelo(filas)
    assert top[0] == {"modelo": "Campera De Jean Hombre Negra", "unidades": 5, "facturado": 50000.0}
    assert top[1]["modelo"] == "Remera Lisa Blanca" and top[1]["unidades"] == 10
    assert top[-1]["modelo"] == "Sin título"


def test_el_top_tiene_tope():
    filas = [(f"Producto {i}", 1, 100 + i) for i in range(20)]
    assert len(chat_ia._consolidar_por_modelo(filas, limite=5)) == 5


def test_hoy_es_la_fecha_argentina_no_la_del_servidor():
    from datetime import datetime, timedelta, timezone
    assert hoy_argentina() == (datetime.now(timezone.utc) - timedelta(hours=3)).date()
    assert chat_ia.hoy_legible() == hoy_argentina().strftime("%Y-%m-%d")

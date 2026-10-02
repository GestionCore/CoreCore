"""Las calificaciones de la reputación: MeLi las manda como proporciones y hoy, en cuentas reales, como "100 % neutral" (sin dato)."""
import reputacion as r


def test_cien_por_ciento_neutral_es_la_ausencia_de_dato():
    """Es lo que MeLi devuelve hoy a cuentas reales (positive 0 / neutral 1 / negative 0): no es "1 calificación" ni "0 % positivas"."""
    assert r.interpretar_ratings({"positive": 0, "neutral": 1, "negative": 0})["disponibles"] is False
    assert r.interpretar_ratings({"positive": 0, "neutral": 0, "negative": 0})["disponibles"] is False
    assert r.interpretar_ratings(None)["disponibles"] is False


def test_proporciones_reales_se_reconocen_como_tales():
    c = r.interpretar_ratings({"positive": 0.96, "neutral": 0.03, "negative": 0.01})
    assert c["disponibles"] and c["son_proporciones"]


def test_cantidades_reales_siguen_disponibles():
    c = r.interpretar_ratings({"positive": 45, "neutral": 3, "negative": 2})
    assert c["disponibles"] and not c["son_proporciones"]
    assert r.interpretar_ratings({"positive": 1, "neutral": 0, "negative": 0})["disponibles"]       # una sola calificación positiva: es un dato
    assert r.interpretar_ratings({"positive": 0, "neutral": 0, "negative": 1})["disponibles"]


def test_una_negativa_con_proporciones_se_muestra():
    assert r.interpretar_ratings({"positive": 0.5, "neutral": 0.25, "negative": 0.25})["disponibles"]

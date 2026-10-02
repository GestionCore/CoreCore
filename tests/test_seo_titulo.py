"""Puntaje SEO de un título: sin la regla falsa de "MeLi trunca a los 60" (los títulos reales miden 62-113)."""
import tendencias as t


def _score(titulo, tendencia=()):
    return t.calcular_seo_score_titulo(titulo, set(tendencia))


def test_un_titulo_largo_no_se_penaliza_por_largo():
    titulo = "Campera Rompeviento Impermeable Hombre Capucha Desmontable Ultraliviana Talle L Azul Marino"      # 90 caracteres
    r = _score(titulo)
    assert len(titulo) > 60 and r["score"] == 100 and not r["razones"]


def test_un_titulo_corto_resta_y_explica_sin_hablar_de_60():
    r = _score("Campera hombre")
    assert r["score"] == 85 and "corto" in r["razones"][0] and "60" not in r["razones"][0]


def test_el_texto_promocional_resta_y_nombra_las_palabras():
    r = _score("Campera Hombre Impermeable OFERTA Envío Gratis Talle L Azul")
    assert r["score"] == 90
    assert "«gratis»" in r["razones"][0] and "«oferta»" in r["razones"][0]


def test_una_palabra_repetida_resta_poco():
    r = _score("Campera Hombre Impermeable Campera Capucha Desmontable Azul")
    assert r["score"] == 95 and "«campera»" in r["razones"][0]


def test_las_palabras_en_tendencia_suman_hasta_20():
    r = _score("Campera Hombre Impermeable Capucha Desmontable Azul Marino Talle L", {"impermeable", "capucha", "azul"})
    assert r["score"] == 100                       # 100 + 20 queda topeado en 100
    assert any(x.startswith("+20") for x in r["razones"])
    r2 = _score("Campera hombre", {"campera"})
    assert r2["score"] == 95                       # 100 - 15 + 10

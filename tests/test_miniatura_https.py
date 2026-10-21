"""
Miniaturas: se guardan siempre con https. Antes `p.get("secure_thumbnail") or p.get("thumbnail")` dejaba pasar el `http://` que manda Mercado Libre (275 de 275 en la base real).
"""
import sincronizador as s


def test_prefiere_la_segura_y_si_no_pasa_la_comun_a_https():
    assert s.miniatura_https({"secure_thumbnail": "https://http2.mlstatic.com/D_1.jpg", "thumbnail": "http://http2.mlstatic.com/D_1.jpg"}) == "https://http2.mlstatic.com/D_1.jpg"
    assert s.miniatura_https({"thumbnail": "http://http2.mlstatic.com/D_2.jpg"}) == "https://http2.mlstatic.com/D_2.jpg"
    assert s.miniatura_https({"secure_thumbnail": "http://http2.mlstatic.com/D_3.jpg"}) == "https://http2.mlstatic.com/D_3.jpg"      # aunque la «segura» venga mal


def test_sin_miniatura_no_inventa_nada():
    assert s.miniatura_https({}) is None
    assert s.miniatura_https({"thumbnail": ""}) is None
    assert s.miniatura_https({"thumbnail": None, "secure_thumbnail": None}) is None


def test_una_url_que_ya_es_https_o_de_otro_tipo_no_se_toca():
    assert s.miniatura_https({"thumbnail": "https://x.example/a.png"}) == "https://x.example/a.png"
    assert s.miniatura_https({"thumbnail": "//x.example/a.png"}) == "//x.example/a.png"

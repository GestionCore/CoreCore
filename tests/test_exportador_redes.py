"""
Exportar una publicación para redes (exportador_redes): la imagen se arma EN MEMORIA (antes cada exportación dejaba un archivo en exports/ para siempre), la foto se baja solo por https
y con tope de tamaño. Sin red: la descarga se simula.
"""
from io import BytesIO

from PIL import Image

import exportador_redes


class _Raw:
    def __init__(self, contenido):
        self.contenido = contenido

    def read(self, cantidad, decode_content=False):
        return self.contenido[:cantidad]


class _Respuesta:
    def __init__(self, contenido, codigo=200):
        self.status_code, self.raw = codigo, _Raw(contenido)


def _foto(ancho=300, alto=200):
    salida = BytesIO()
    Image.new("RGB", (ancho, alto), (200, 30, 30)).save(salida, "PNG")
    return salida.getvalue()


def _con_foto(monkeypatch, respuesta, pedidos=None):
    def _get(url, **k):
        if pedidos is not None:
            pedidos.append((url, k))
        return respuesta
    monkeypatch.setattr(exportador_redes.requests, "get", _get)


def test_sin_ruta_la_imagen_queda_en_memoria_y_es_un_png_cuadrado(monkeypatch, tmp_path):
    _con_foto(monkeypatch, _Respuesta(_foto()))
    monkeypatch.chdir(tmp_path)
    salida = exportador_redes.generar_imagen_publicacion("https://http2.mlstatic.com/foto.jpg", "Termo de acero", "12.500")
    assert isinstance(salida, BytesIO) and salida.read(8) == b"\x89PNG\r\n\x1a\n"
    salida.seek(0)
    assert Image.open(salida).size == (1080, 1080)
    assert list(tmp_path.iterdir()) == []                                                  # nada escrito en disco


def test_con_ruta_se_escribe_el_archivo_y_se_devuelve_la_ruta(monkeypatch, tmp_path):
    _con_foto(monkeypatch, _Respuesta(_foto()))
    ruta = str(tmp_path / "post.png")
    assert exportador_redes.generar_imagen_publicacion("https://x.test/f.jpg", "Termo", "1", ruta_salida=ruta) == ruta
    assert Image.open(ruta).size == (1080, 1080)


def test_una_miniatura_con_http_se_pide_por_https(monkeypatch):
    pedidos = []
    _con_foto(monkeypatch, _Respuesta(_foto()), pedidos)
    assert exportador_redes.generar_imagen_publicacion("http://http2.mlstatic.com/foto.jpg", "Termo", "1") is not None
    assert pedidos[0][0] == "https://http2.mlstatic.com/foto.jpg" and pedidos[0][1]["timeout"] == 10


def test_solo_se_descarga_por_http_o_https(monkeypatch):
    pedidos = []
    _con_foto(monkeypatch, _Respuesta(_foto()), pedidos)
    for url in ("file:///etc/passwd", "ftp://x.test/f.jpg", "//x.test/f.jpg", "", None):
        assert exportador_redes.generar_imagen_publicacion(url, "Termo", "1") is None
    assert pedidos == []


def test_una_foto_demasiado_grande_no_se_exporta(monkeypatch):
    monkeypatch.setattr(exportador_redes, "MAX_BYTES_FOTO", 1000)
    _con_foto(monkeypatch, _Respuesta(b"x" * 5000))
    assert exportador_redes.generar_imagen_publicacion("https://x.test/f.jpg", "Termo", "1") is None


def test_si_la_descarga_falla_o_no_es_una_imagen_devuelve_none(monkeypatch):
    _con_foto(monkeypatch, _Respuesta(b"", codigo=404))
    assert exportador_redes.generar_imagen_publicacion("https://x.test/f.jpg", "Termo", "1") is None
    _con_foto(monkeypatch, _Respuesta(b"esto no es una imagen"))
    assert exportador_redes.generar_imagen_publicacion("https://x.test/f.jpg", "Termo", "1") is None


def test_un_titulo_largo_se_corta_sin_romper(monkeypatch):
    _con_foto(monkeypatch, _Respuesta(_foto()))
    assert exportador_redes.generar_imagen_publicacion("https://x.test/f.jpg", "Campera " * 40, "1.000.000") is not None

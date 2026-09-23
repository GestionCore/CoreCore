"""
Exportador de Catálogo a Redes: genera una imagen cuadrada (formato
Instagram/Facebook) con la foto del producto, el precio y tu marca, lista
para postear — sin tener que armarla a mano en otro programa.
"""
import os
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

TAMANO_LIENZO = 1080
ALTO_BARRA_INFERIOR = 220
FUENTE_BOLD = os.path.join(os.path.dirname(__file__), "static", "fonts", "DejaVuSans-Bold.ttf")
FUENTE_NORMAL = os.path.join(os.path.dirname(__file__), "static", "fonts", "DejaVuSans.ttf")

COLOR_FONDO = (13, 17, 23)
COLOR_BARRA = (15, 18, 26)
COLOR_ACENTO = (245, 166, 35)
COLOR_TEXTO = (244, 246, 251)


def generar_imagen_publicacion(url_foto, titulo, precio_formateado, marca="Santi Mens", ruta_salida=None):
    """
    Descarga la foto de la publicación y arma una pieza cuadrada lista para
    redes: foto arriba, barra inferior con precio y marca. Devuelve la ruta
    del archivo generado, o None si no se pudo descargar la foto.
    """
    try:
        resp = requests.get(url_foto, timeout=10)
        if resp.status_code != 200:
            return None
        foto = Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        print(f"[Exportador Redes] ⚠️ Error descargando la foto: {e}")
        return None

    lienzo = Image.new("RGB", (TAMANO_LIENZO, TAMANO_LIENZO), COLOR_FONDO)

    # Foto: recorte centrado para llenar el área superior sin deformarla
    alto_foto_area = TAMANO_LIENZO - ALTO_BARRA_INFERIOR
    ratio_area = TAMANO_LIENZO / alto_foto_area
    ratio_foto = foto.width / foto.height

    if ratio_foto > ratio_area:
        nuevo_alto = alto_foto_area
        nuevo_ancho = int(nuevo_alto * ratio_foto)
    else:
        nuevo_ancho = TAMANO_LIENZO
        nuevo_alto = int(nuevo_ancho / ratio_foto)

    foto_redim = foto.resize((nuevo_ancho, nuevo_alto), Image.LANCZOS)
    offset_x = (nuevo_ancho - TAMANO_LIENZO) // 2
    offset_y = (nuevo_alto - alto_foto_area) // 2
    foto_recortada = foto_redim.crop((offset_x, offset_y, offset_x + TAMANO_LIENZO, offset_y + alto_foto_area))
    lienzo.paste(foto_recortada, (0, 0))

    draw = ImageDraw.Draw(lienzo)
    draw.rectangle([0, alto_foto_area, TAMANO_LIENZO, TAMANO_LIENZO], fill=COLOR_BARRA)
    draw.rectangle([0, alto_foto_area, TAMANO_LIENZO, alto_foto_area + 4], fill=COLOR_ACENTO)

    try:
        fuente_precio = ImageFont.truetype(FUENTE_BOLD, 64)
        fuente_titulo = ImageFont.truetype(FUENTE_NORMAL, 30)
        fuente_marca = ImageFont.truetype(FUENTE_BOLD, 28)
    except Exception:
        fuente_precio = fuente_titulo = fuente_marca = ImageFont.load_default()

    titulo_corto = (titulo[:52] + "…") if len(titulo) > 52 else titulo
    draw.text((40, alto_foto_area + 24), titulo_corto, font=fuente_titulo, fill=(160, 168, 184))
    draw.text((40, alto_foto_area + 65), f"${precio_formateado}", font=fuente_precio, fill=COLOR_TEXTO)
    draw.text((40, TAMANO_LIENZO - 55), marca.upper(), font=fuente_marca, fill=COLOR_ACENTO)

    if not ruta_salida:
        ruta_salida = "/tmp/export_red.png"
    lienzo.save(ruta_salida, "PNG", quality=95)
    return ruta_salida

"""
"Exportar cualquier gráfico como imagen" — pedido explícito. En vez de
sumar una librería de canvas/JS (html2canvas y similares son pesadas y
frágiles con backdrop-filter/gradientes CSS), el gráfico se re-dibuja
del lado del servidor con Pillow (ya era dependencia, por
exportador_redes.py) usando los mismos colores reales de la marca —
así el PNG que baja el usuario se ve igual que en pantalla, no una
captura rara.

Pensado para reusarse: cualquier gráfico de barras nuevo llama
`generar_barras_png()` con su propia serie de datos.
"""
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from utils import formatear_moneda

FUENTE_BOLD = os.path.join(os.path.dirname(__file__), "static", "fonts", "DejaVuSans-Bold.ttf")
FUENTE_NORMAL = os.path.join(os.path.dirname(__file__), "static", "fonts", "DejaVuSans.ttf")

COLOR_FONDO = (10, 11, 26)         # --bg-surface
COLOR_BARRA_ARRIBA = (176, 107, 255)   # --accent-primary
COLOR_BARRA_ABAJO = (139, 63, 252)     # --accent-primary-dim
COLOR_TEXTO_PRIMARIO = (247, 247, 255)  # --text-primary
COLOR_TEXTO_SECUNDARIO = (148, 148, 184)  # --text-secondary
COLOR_MARCA = (245, 166, 35)       # dorado de la marca


def generar_barras_png(serie, titulo, subtitulo=None, ancho=1000, alto=420, marca="CoreLux"):
    """
    serie: [{"etiqueta": "10/09", "valor": 1234.0}, ...]
    Devuelve un BytesIO con el PNG, listo para send_file.
    """
    img = Image.new("RGB", (ancho, alto), COLOR_FONDO)
    draw = ImageDraw.Draw(img)

    try:
        f_titulo = ImageFont.truetype(FUENTE_BOLD, 26)
        f_subtitulo = ImageFont.truetype(FUENTE_NORMAL, 16)
        f_eje = ImageFont.truetype(FUENTE_NORMAL, 13)
        f_marca = ImageFont.truetype(FUENTE_BOLD, 14)
    except Exception:
        f_titulo = f_subtitulo = f_eje = f_marca = ImageFont.load_default()

    margen_izq, margen_der, margen_arriba, margen_abajo = 50, 50, 80, 70
    draw.text((margen_izq, 26), titulo, font=f_titulo, fill=COLOR_TEXTO_PRIMARIO)
    if subtitulo:
        draw.text((margen_izq, 58), subtitulo, font=f_subtitulo, fill=COLOR_TEXTO_SECUNDARIO)

    area_x0, area_y0 = margen_izq, margen_arriba
    area_x1, area_y1 = ancho - margen_der, alto - margen_abajo
    area_alto = area_y1 - area_y0

    valores = [max(p.get("valor", 0), 0) for p in serie] or [0]
    maximo = max(valores) or 1
    n = len(serie) or 1
    gap = 6
    ancho_barra = ((area_x1 - area_x0) - gap * (n - 1)) / n if n else 0

    for i, punto in enumerate(serie):
        valor = max(punto.get("valor", 0), 0)
        alto_barra = (valor / maximo) * area_alto if maximo else 0
        x0 = area_x0 + i * (ancho_barra + gap)
        x1 = x0 + ancho_barra
        y1 = area_y1
        y0 = y1 - max(alto_barra, 2)

        # Gradiente vertical simple para esta barra
        for y in range(int(y0), int(y1)):
            t = (y - y0) / (y1 - y0) if y1 > y0 else 0
            r = int(COLOR_BARRA_ARRIBA[0] + (COLOR_BARRA_ABAJO[0] - COLOR_BARRA_ARRIBA[0]) * t)
            g = int(COLOR_BARRA_ARRIBA[1] + (COLOR_BARRA_ABAJO[1] - COLOR_BARRA_ARRIBA[1]) * t)
            b = int(COLOR_BARRA_ARRIBA[2] + (COLOR_BARRA_ABAJO[2] - COLOR_BARRA_ARRIBA[2]) * t)
            draw.line([(x0, y), (x1, y)], fill=(r, g, b))

        etiqueta = punto.get("etiqueta", "")
        bbox = draw.textbbox((0, 0), etiqueta, font=f_eje)
        ancho_txt = bbox[2] - bbox[0]
        draw.text((x0 + (ancho_barra - ancho_txt) / 2, area_y1 + 10), etiqueta, font=f_eje, fill=COLOR_TEXTO_SECUNDARIO)

    draw.text((margen_izq, alto - 34), marca.upper(), font=f_marca, fill=COLOR_MARCA)

    buffer = BytesIO()
    img.save(buffer, "PNG")
    buffer.seek(0)
    return buffer

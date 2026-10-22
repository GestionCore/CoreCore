"""
Genera la imagen que se ve al compartir CoreLux (static/icons/og-corelux.png, 1200 × 630): la que aparece en la vista previa de Facebook, WhatsApp, Telegram y X.

Antes la vista previa mostraba el ícono cuadrado de la app. Esta usa la misma identidad (grafito, violeta y dorado), la frase de la landing y un recuadro con DATOS DE EJEMPLO
rotulados (nunca números reales de una cuenta: es una imagen pública).

Uso (desde CoreLux-SaaS, con el venv activo):  python generar_og.py
Usa las tipografías del sistema (Georgia para el título, Arial para el resto): las de la web son .woff2 y Pillow no las abre.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import generar_iconos

RAIZ = os.path.dirname(os.path.abspath(__file__))
ANCHO, ALTO = 1200, 630
SUPER = 2                                    # se dibuja al doble y se achica: bordes suaves

GRAFITO = (10, 10, 12)
BLANCO = (255, 255, 255)
GRIS = (148, 163, 184)
GRIS_OSCURO = (122, 132, 150)
ORO = (242, 201, 76)
VIOLETA = (139, 92, 246)
VERDE = (34, 197, 94)
ROJO = (244, 63, 94)
CELESTE = (56, 189, 248)
NARANJA = (240, 161, 59)

CARPETA_FUENTES = os.environ.get("CARPETA_FUENTES", r"C:\Windows\Fonts")


def _fuente(nombre, tam):
    return ImageFont.truetype(os.path.join(CARPETA_FUENTES, nombre), tam * SUPER)


def _s(v):
    return round(v * SUPER)


def _texto(d, xy, texto, fuente, color, ancla="la"):
    d.text((_s(xy[0]), _s(xy[1])), texto, font=fuente, fill=color, anchor=ancla)


def _fondo():
    """Grafito con dos resplandores violeta suaves (como el de la landing)."""
    img = Image.new("RGB", (ANCHO * SUPER, ALTO * SUPER), GRAFITO)
    brillo = Image.new("RGB", img.size, GRAFITO)
    d = ImageDraw.Draw(brillo)
    d.ellipse([_s(700), _s(-260), _s(1360), _s(330)], fill=(60, 36, 120))
    d.ellipse([_s(-200), _s(380), _s(380), _s(860)], fill=(30, 20, 60))
    brillo = brillo.filter(ImageFilter.GaussianBlur(_s(150)))
    return Image.blend(img, brillo, 0.85)


def _tarjeta(img):
    """El recuadro de la derecha: la pantalla Ganancia Real con datos de ejemplo."""
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    x0, y0, x1, y1 = 650, 150, 1130, 500
    d.rounded_rectangle([_s(x0), _s(y0), _s(x1), _s(y1)], radius=_s(22), fill=(20, 20, 26, 235), outline=(60, 60, 74, 255), width=_s(2))
    pequena, mediana, grande, etiqueta = _fuente("arialbd.ttf", 15), _fuente("arial.ttf", 17), _fuente("arialbd.ttf", 62), _fuente("arialbd.ttf", 14)
    _texto(d, (x0 + 32, y0 + 30), "GANANCIA NETA REAL · 30 DÍAS", etiqueta, GRIS)
    _texto(d, (x1 - 32, y0 + 30), "DATOS DE EJEMPLO", etiqueta, GRIS_OSCURO, "ra")
    _texto(d, (x0 + 32, y0 + 62), "$2.366.000", grande, BLANCO)
    _texto(d, (x0 + 32, y0 + 140), "De $8.450.000 facturados, te quedó el 28 %.", mediana, GRIS)
    # barra de reparto (comisión, envíos, publicidad, fabricación, te queda)
    barra_x0, barra_x1, barra_y = x0 + 32, x1 - 32, y0 + 188
    tramos = ((17, ROJO), (11, CELESTE), (9, NARANJA), (35, VIOLETA), (28, VERDE))
    ancho_total = barra_x1 - barra_x0 - 4 * 4
    x = barra_x0
    for peso, color in tramos:
        w = ancho_total * peso / 100
        d.rounded_rectangle([_s(x), _s(barra_y), _s(x + w), _s(barra_y + 14)], radius=_s(7), fill=color)
        x += w + 4
    # leyenda
    filas = (("Comisión", "$1.436.500", ROJO), ("Envíos", "$929.500", CELESTE), ("Publicidad", "$760.500", NARANJA), ("Fabricación", "$2.957.500", VIOLETA))
    y = y0 + 226
    for nombre, valor, color in filas:
        d.ellipse([_s(x0 + 34), _s(y + 6), _s(x0 + 46), _s(y + 18)], fill=color)
        _texto(d, (x0 + 58, y), nombre, pequena, GRIS)
        _texto(d, (x1 - 32, y), valor, _fuente("arialbd.ttf", 15), BLANCO, "ra")
        y += 27
    img.paste(capa, (0, 0), capa)


def main():
    img = _fondo().convert("RGBA")
    d = ImageDraw.Draw(img)

    # marca y nombre
    marca = generar_iconos._marca(_s(56), 0.62)
    img.alpha_composite(marca, (_s(70), _s(58)))
    _texto(d, (140, 86), "CoreLux", _fuente("georgiab.ttf", 34), BLANCO, "lm")

    # titular (la frase de la landing; «de verdad» en dorado). La columna del texto llega hasta x = 600: a partir de 650 está el recuadro.
    titulo = _fuente("georgiab.ttf", 62)
    _texto(d, (70, 160), "Sabé cuánto te", titulo, BLANCO)
    _texto(d, (70, 236), "queda ", titulo, BLANCO)
    ancho_queda = d.textlength("queda ", font=titulo) / SUPER
    _texto(d, (70 + ancho_queda, 236), "de verdad", titulo, ORO)
    _texto(d, (70, 312), "de cada venta.", titulo, BLANCO)

    # bajada
    bajada = _fuente("arial.ttf", 23)
    for n, linea in enumerate(("Comisión, cuotas, envío, publicidad y", "costo de lo que vendés en Mercado Libre,", "ya descontados.")):
        _texto(d, (70, 432 + 33 * n), linea, bajada, GRIS)

    # píldora de beta y dirección
    d.rounded_rectangle([_s(70), _s(552), _s(268), _s(594)], radius=_s(21), fill=(40, 28, 78), outline=VIOLETA, width=_s(2))
    _texto(d, (169, 573), "Beta cerrada · gratis", _fuente("arialbd.ttf", 18), (196, 181, 253), "mm")
    _texto(d, (1130, 573), "corelux.app", _fuente("arialbd.ttf", 22), GRIS, "rm")

    _tarjeta(img)

    final = img.convert("RGB").resize((ANCHO, ALTO), Image.LANCZOS)
    destino = os.path.join(RAIZ, "static", "icons", "og-corelux.png")
    final.save(destino, optimize=True)
    print("Imagen para compartir generada en", destino, f"({os.path.getsize(destino) // 1024} KB)")


if __name__ == "__main__":
    main()

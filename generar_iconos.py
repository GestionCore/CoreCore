"""
Genera los íconos de la app instalable (static/icons/*.png y static/favicon.ico) con la identidad vigente: fondo grafito (#0a0a0c) y la marca en dorado (#f2c94c → #d4a017),
una «C» abierta con un punto en el centro (el «núcleo»). Los íconos anteriores eran una «S» naranja de la app original (Santi Mens), que no es esta marca.

Uso (desde CoreLux-SaaS, con el venv activo):  python generar_iconos.py
- icon-192.png / icon-512.png: ícono normal (esquinas redondeadas)
- icon-maskable-512.png: ocupa todo el cuadrado y la marca queda dentro del 60 % central (el sistema le recorta la forma que quiera)
- icon-180.png: el de iOS (cuadrado: iOS le pone sus propias esquinas) · icon-32.png y favicon.ico: pestaña del navegador
"""
import math
import os

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.abspath(__file__))
GRAFITO = (10, 10, 12)
ORO_CLARO = (242, 201, 76)
ORO_OSCURO = (212, 160, 23)
SUPER = 4                      # se dibuja 4 veces más grande y se achica: bordes suaves


def _gradiente(n):
    """Cuadrado n × n con el degradado dorado en diagonal."""
    img = Image.new("RGB", (n, n))
    px = img.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            px[x, y] = tuple(round(ORO_CLARO[i] + (ORO_OSCURO[i] - ORO_CLARO[i]) * t) for i in range(3))
    return img


def _marca(n, escala):
    """La marca (C + núcleo) sobre fondo transparente, en un cuadrado n × n. `escala` = qué fracción del cuadrado ocupa el diámetro exterior."""
    g = n * SUPER
    mascara = Image.new("L", (g, g), 0)
    d = ImageDraw.Draw(mascara)
    centro = g / 2
    radio = g * escala / 2
    grosor = radio * 0.36
    caja = [centro - radio, centro - radio, centro + radio, centro + radio]
    d.arc(caja, start=42, end=318, fill=255, width=round(grosor))                    # la «C»: abierta a la derecha
    for angulo in (42, 318):                                                         # puntas redondeadas
        a = math.radians(angulo)
        r_medio = radio - grosor / 2
        cx, cy = centro + r_medio * math.cos(a), centro + r_medio * math.sin(a)
        d.ellipse([cx - grosor / 2, cy - grosor / 2, cx + grosor / 2, cy + grosor / 2], fill=255)
    nucleo = radio * 0.2
    d.ellipse([centro - nucleo, centro - nucleo, centro + nucleo, centro + nucleo], fill=255)           # el punto del centro
    mascara = mascara.resize((n, n), Image.LANCZOS)
    oro = _gradiente(n).convert("RGBA")
    oro.putalpha(mascara)
    return oro


def _icono(n, redondeado, escala):
    fondo = Image.new("RGBA", (n, n), GRAFITO + (255,))
    fondo.alpha_composite(_marca(n, escala))
    if redondeado:
        g = n * SUPER
        mascara = Image.new("L", (g, g), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([0, 0, g - 1, g - 1], radius=round(g * 0.22), fill=255)
        fondo.putalpha(mascara.resize((n, n), Image.LANCZOS))
    return fondo


def main():
    iconos = os.path.join(RAIZ, "static", "icons")
    _icono(512, True, 0.62).save(os.path.join(iconos, "icon-512.png"))
    _icono(192, True, 0.62).save(os.path.join(iconos, "icon-192.png"))
    _icono(512, False, 0.46).save(os.path.join(iconos, "icon-maskable-512.png"))      # marca dentro de la zona segura (el 60 % central)
    _icono(180, False, 0.62).save(os.path.join(iconos, "icon-180.png"))
    _icono(32, True, 0.66).save(os.path.join(iconos, "icon-32.png"))
    ico = [_icono(n, True, 0.66) for n in (16, 32, 48)]
    ico[2].save(os.path.join(RAIZ, "static", "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    print("Íconos generados en", iconos)


if __name__ == "__main__":
    main()

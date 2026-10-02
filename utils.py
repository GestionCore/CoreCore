"""Utilidades compartidas entre páginas — portadas tal cual de Santi Mens."""
import re
from datetime import datetime, timedelta, timezone

ARGENTINA = timezone(timedelta(hours=-3))      # sin horario de verano


def hoy_argentina():
    """La fecha de hoy en Argentina (el servidor corre en UTC: pasadas las 21 h, "hoy" ya sería mañana)."""
    return datetime.now(ARGENTINA).date()


ESTADOS_INCIDENCIA_LEGIBLES = {
    "open": "Abierto", "opened": "Abierto",
    "closed": "Cerrado",
    "claim": "Reclamo activo",
    "dispute": "En mediación",
    "mediation": "En mediación",
    "resolved": "Resuelto",
    "none": "Sin etapa",
}


# Un reclamo es "grave" (cuenta en el ticker, resta puntos de Salud, es una misión urgente) solo si Mercado Libre dice que afecta la
# reputación. Mientras no se sabe (NULL) se cuenta igual, por prudencia. Para usar dentro de un WHERE sobre incidencias_posventa.
SQL_RECLAMO_AFECTA = "(afecta_reputacion IS NULL OR afecta_reputacion = 'affected')"


def formatear_estado_incidencia(estado):
    return ESTADOS_INCIDENCIA_LEGIBLES.get((estado or "").lower(), (estado or "Sin dato").capitalize())


def formatear_moneda(valor):
    try:
        val = float(valor or 0.0)
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "0,00"


def formatear_moneda_entera(valor):
    """
    Igual que formatear_moneda pero sin centavos — para números "hero"
    en letra grande, donde mostrar ",00" es ruido visual. Misma lógica
    de separador de miles (punto) que el resto de la app, para no
    reinventar el formateo con un f-string suelto en cada lugar nuevo.
    """
    try:
        val = float(valor or 0.0)
        return f"{val:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


# Talle: la fuente confiable es el atributo SIZE que Mercado Libre trae en cada ítem (el sincronizador lo guarda en
# productos_variantes.talle). El título es solo el respaldo, y como CoreLux lo usan vendedores de cualquier rubro, ahí solo se
# acepta lo que parece un talle: letras (S, M, L, XL, XXL, XXXL), "talle N" explícito o un número de 1-2 dígitos AL FINAL del título
# ("... Inflable 7"). Un número en el medio ("Combo 2 Termos", "Perfume 50 ml") no es un talle.
_RE_TALLE_EXPLICITO = re.compile(r'\b(?:talle|size)\s*[:#]?\s*(XXXL|XXL|XL|L|M|S|\d+)\b', re.IGNORECASE)
_RE_TALLE_LETRAS = re.compile(r'\b(XXXL|XXL|XL|L|M|S)\b', re.IGNORECASE)
_RE_TALLE_AL_FINAL = re.compile(r'\s(\d{1,2})\s*$')


def extraer_talle(titulo, talle_real=None):
    """El talle de una publicación: el real (atributo de MeLi) si se conoce; si no, el que se deduce del título; si no, "Único"."""
    if talle_real and str(talle_real).strip() and talle_real != "Único":
        return str(talle_real).strip().upper()
    if not titulo:
        return "Único"
    m = _RE_TALLE_EXPLICITO.search(titulo) or _RE_TALLE_LETRAS.search(titulo) or _RE_TALLE_AL_FINAL.search(titulo)
    return m.group(1).upper() if m else "Único"


def limpiar_titulo_modelo(titulo):
    # titulo puede llegar None (venta sincronizada antes de tener el título
    # cacheado, publicación borrada del lado de MeLi, etc.) — re.sub explota
    # con NoneType en vez de string, y esta función se llama desde Despacho,
    # Stock, Stock Masivo, Catálogo, Dashboard, Tendencias y Análisis de
    # Stock, así que un solo título nulo tiraba 500/502 en cualquiera de esas
    # páginas y, en listados, cortaba el resto de las filas de golpe.
    if not titulo:
        return ""
    t = re.sub(r'\b(talle|size)\s*[:#]?\s*(xxxl|xxl|xl|l|m|s|\d+)\b', '', titulo, flags=re.IGNORECASE)
    t = re.sub(r'\b(xxxl|xxl|xl|l|m|s)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+\d{1,2}\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def plata(valor, decimales=0):
    """
    "$1.234.567" — formato único de plata para pantallas y filtros Jinja
    ({{ valor|plata }}). Signo adelante del $ ("-$1.500"), punto de miles,
    coma decimal. Devuelve "—" si no hay dato, para no mostrar un $0 falso.
    """
    try:
        val = float(valor)
    except (TypeError, ValueError):
        return "—"
    texto = f"{abs(val):,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if val < 0 else "") + "$" + texto


def porcentaje(valor, decimales=1):
    """"12,5%" — coma decimal, sin ceros de más. "—" si no hay dato."""
    try:
        val = float(valor)
    except (TypeError, ValueError):
        return "—"
    texto = f"{val:.{decimales}f}".rstrip("0").rstrip(".") if decimales else f"{val:.0f}"
    return texto.replace(".", ",") + "%"


def numero(valor):
    """Entero con punto de miles: 12.345. "—" si no hay dato."""
    try:
        return f"{float(valor):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


# ── HTML seguro para las macros de _ux.html ─────────────────────────────────────────────────────────────────────────────────────
# Los textos de banners y KPI se arman con un poco de HTML ("<b>3 reclamos</b>") y a veces mezclan datos que vienen de afuera (títulos de
# Mercado Libre, nombres de compradores). En vez de confiar en que cada llamador escape lo suyo, la macro deja pasar solo un conjunto
# chico de etiquetas y atributos y escapa todo lo demás.
import html as _html
from html.parser import HTMLParser as _HTMLParser

_ETIQUETAS_OK = {"b", "strong", "i", "em", "u", "small", "span", "br", "a"}
_ATRIBUTOS_OK = {"class", "title", "style", "href", "target", "rel"}
_DESCARTAR_CONTENIDO = {"script", "style", "iframe", "object", "embed"}


def _atributo_seguro(nombre, valor):
    valor = valor or ""
    if nombre == "href":
        return valor.startswith(("/", "#", "https://", "mailto:"))
    if nombre == "style":
        return not any(x in valor.lower() for x in ("url(", "javascript", "expression", "@import", "behavior"))
    if nombre == "target":
        return valor == "_blank"
    return True


class _Saneador(_HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.salida, self._saltar = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _DESCARTAR_CONTENIDO:
            self._saltar += 1
            return
        if tag not in _ETIQUETAS_OK or self._saltar:
            return
        atributos = "".join(f' {n}="{_html.escape(v or "", quote=True)}"' for n, v in attrs if n in _ATRIBUTOS_OK and _atributo_seguro(n, v))
        if tag == "a" and 'target="_blank"' in atributos:
            atributos += ' rel="noopener"'
        self.salida.append(f"<{tag}{atributos}>")

    def handle_endtag(self, tag):
        if tag in _DESCARTAR_CONTENIDO:
            self._saltar = max(0, self._saltar - 1)
        elif tag in _ETIQUETAS_OK and tag != "br" and not self._saltar:
            self.salida.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._saltar:
            self.salida.append(_html.escape(data, quote=False))


def html_seguro(texto):
    """Deja pasar solo <b>, <i>, <span>, <a>, <br>… con atributos inofensivos; todo lo demás se escapa o se descarta."""
    if not texto:
        return ""
    p = _Saneador()
    p.feed(str(texto))
    p.close()
    return "".join(p.salida)

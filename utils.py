"""Utilidades compartidas entre páginas — portadas tal cual de Santi Mens."""
import re
from datetime import datetime, timedelta, timezone

ARGENTINA = timezone(timedelta(hours=-3))      # sin horario de verano


def sql_momento_argentina(prefijo="", por_defecto="00:00"):
    """
    Fragmento SQL: el momento de la venta (fecha + hora) en HORA ARGENTINA. Las filas viejas guardan la hora de Mercado Libre tal cual (UTC-4, una hora
    atrasada) y las nuevas ya vienen en hora argentina (ventas.hora_normalizada = true, ver ventas_sync y normalizar_horas.py): esta expresión da el
    mismo resultado para unas y otras, así que el código es correcto antes y después de normalizar el histórico. Usarla para todo lo que dependa de la
    HORA (mapa de horarios, "cuándo te compran", corte de despacho). `por_defecto` reemplaza una hora NULL.
    """
    if not re.fullmatch(r"\d{2}:\d{2}", por_defecto) or not re.fullmatch(r"\w*", prefijo):
        raise ValueError("argumentos inválidos para sql_momento_argentina")
    p = prefijo + "." if prefijo else ""
    return (f"({p}fecha_venta + COALESCE({p}hora_venta, TIME '{por_defecto}') "
            f"+ CASE WHEN {p}hora_normalizada THEN INTERVAL '0 hour' ELSE INTERVAL '1 hour' END)")


def vocabulario(usa_talles):
    """
    Cómo llamar a las variantes de una publicación en pantalla. CoreLux lo usan vendedores de todos los rubros: quien vende ropa o calzado ve "talle", y
    quien vende electrónica o artículos sin variantes ve "variante" (no "talle"). `usa_talles` es True si la cuenta tiene al menos un talle real.
    """
    return {"v1": "talle", "vN": "talles", "V1": "Talle", "VN": "Talles"} if usa_talles else {"v1": "variante", "vN": "variantes", "V1": "Variante", "VN": "Variantes"}


def cuenta_usa_talles(cursor):
    """True si alguna variante de la cuenta tiene un talle real (no vacío ni "Único"): decide si se habla de "talles" o de "variantes"."""
    cursor.execute("SELECT EXISTS(SELECT 1 FROM productos_variantes WHERE talle IS NOT NULL AND talle NOT IN ('', 'Único'))")
    return bool(cursor.fetchone()[0])


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
    """
    "1.234.567" — pesos enteros con punto de miles, sin el "$" (cada pantalla lo antepone). Antes llevaba centavos ("1.234.567,89") y las pantallas
    mezclaban montos con y sin ",00" una al lado de la otra: en análisis de ventas los centavos no cambian ninguna decisión y solo agregan ruido.
    Los exports (Excel) usan los valores numéricos, no este texto.
    """
    try:
        val = round(float(valor or 0.0))                # round() da un int: nunca "-0" para un -0,4
        return f"{val:,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


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


def plural(cantidad, singular, plural_=None):
    """'1 venta' / '3 ventas' / '2 devoluciones' (con el plural explícito cuando no alcanza con agregar una s). Nunca 'venta(s)'."""
    try:
        n = float(cantidad)
    except (TypeError, ValueError):
        n = 0
    palabra = singular if n == 1 else (plural_ or singular + "s")
    return f"{numero(cantidad)} {palabra}"


_RE_PLURAL_VIEJO = re.compile(r"(\w+)\((es|s)\)")


def corregir_plurales(texto):
    """
    Para textos YA GUARDADOS con el formato viejo ("1 reclamo(s) sin resolver", "3 devolución(es)"): decide singular o plural según el primer
    número del texto. Los textos nuevos se arman con plural(); esto es solo para lo que quedó en la base (historial de Logros).
    """
    if not texto or "(" not in texto:
        return texto
    m = re.search(r"\d+", texto)
    uno = bool(m) and m.group() == "1"

    def reemplazar(r):
        palabra, sufijo = r.group(1), r.group(2)
        if uno:
            return palabra
        if sufijo == "es" and palabra.endswith("ón"):
            return palabra[:-2] + "ones"
        return palabra + sufijo

    return _RE_PLURAL_VIEJO.sub(reemplazar, texto)


def ver_mas(n, uno, varios, articulo="las"):
    """Texto del botón de "ver más": 'Ver 1 publicación más' / 'Ver las 5 publicaciones restantes' (antes decía 'Ver las 1 restantes')."""
    n = int(n)
    return f"Ver 1 {uno} más" if n == 1 else f"Ver {articulo} {n} {varios} restantes"


# ── Fechas para mostrar ───────────────────────────────────────────────────────────────────────────────────────────────────────
# En pantalla una fecha se lee como "2 sep" o "2 sep – 2 oct", nunca "2026-09-02": el formato ISO es para la base, no para personas.
MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _a_fecha(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if hasattr(valor, "year") and hasattr(valor, "month"):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fecha_corta(valor, con_anio=None):
    """'2 sep' (o '2 sep 2025' si no es de este año o se pide). Acepta date, datetime o 'AAAA-MM-DD'. '—' si no hay dato."""
    d = _a_fecha(valor)
    if not d:
        return str(valor) if valor not in (None, "") else "—"       # un texto que no es fecha ISO ("hace 2 días") se muestra tal cual
    if con_anio is None:
        con_anio = d.year != hoy_argentina().year
    return f"{d.day} {MESES_CORTOS[d.month - 1]}" + (f" {d.year}" if con_anio else "")


def rango_fechas(desde, hasta):
    """'2 sep – 2 oct', '5 – 12 oct' (mismo mes), '28 dic 2025 – 3 ene' (cruza de año). '—' si falta alguna punta."""
    a, b = _a_fecha(desde), _a_fecha(hasta)
    if not a or not b:
        return "—"
    if a == b:
        return fecha_corta(a)
    if a.year == b.year and a.month == b.month:
        return f"{a.day} – {fecha_corta(b)}"
    return f"{fecha_corta(a, con_anio=a.year != b.year or None)} – {fecha_corta(b)}"


def cuando_corto(momento, con_hora=True):
    """Para listas de actividad: 'Hoy 14:32', 'Ayer 21:05', '30 sep 18:10'. Sin hora conocida, solo el día."""
    if momento is None:
        return "—"
    d = _a_fecha(momento)
    hoy = hoy_argentina()
    dia = "Hoy" if d == hoy else ("Ayer" if d == hoy - timedelta(days=1) else fecha_corta(d))
    if con_hora and isinstance(momento, datetime):
        return f"{dia} {momento:%H:%M}"
    return dia


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

"""
Zonas de cobertura de Mercado Envíos Flex (AMBA) y cómo ubicar un envío en una de ellas.

MeLi define las zonas del servicio Flex de cada vendedor (GET /flex/sites/{site}/users/{user}/services/{service}/
configurations/coverage/zones/v1) pero el envío NO dice a qué zona pertenece: trae la localidad de destino
("Quilmes Oeste", "Hudson", "Caballito"), el partido a veces, y las coordenadas exactas. Este módulo hace ese paso:

  1. Capital Federal → zona CABA.
  2. El nombre de la localidad contra la lista de localidades de cada partido (abajo).
  3. Si no está en la lista, la zona cuyo centro queda más cerca (hasta MAX_KM_FALLBACK): sirve para localidades
     que no conocemos; no reemplaza a la lista.

Lo que no se pueda ubicar queda en None y cae en el umbral "resto". Las zonas que MeLi parte en varias
(La Matanza 1 y 2, La Plata centro/norte/oeste) se tratan como una "familia": ver `familia_de_zona`.
"""
import math
import re
import unicodedata

MAX_KM_FALLBACK = 9.0


def normalizar(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


# ── Nombres de zona legibles ───────────────────────────────────────────────

def nombre_zona(zona_id):
    """"Almirante_Brown" → "Almirante Brown", "AR-B-LA-PLATA-CENTRO" → "La Plata Centro", "AR-B-Garin" → "Garin"."""
    z = re.sub(r"^AR-B-", "", zona_id or "")
    z = z.replace("_", " ").replace("-", " ").strip()
    if z.isupper() and z != "CABA":
        z = z.title()
    return z


def familia_de_zona(zona_id):
    """La_Matanza_1 / La_Matanza_2 → "la matanza"; AR-B-LA-PLATA-NORTE → "la plata". El resto es su propia familia."""
    base = normalizar(nombre_zona(zona_id))
    base = re.sub(r"\s+\d+$", "", base)
    base = re.sub(r"\s+(centro|norte|oeste|sur|este)$", "", base) if base.startswith("la plata") else base
    return base


# ── Localidades de cada partido (nombre normalizado → familia de zona) ─────

_LOCALIDADES = {
    "almirante brown": ["almirante brown", "adrogue", "burzaco", "claypole", "don orione", "glew", "jose marmol", "longchamps",
                        "ministro rivadavia", "rafael calzada", "san jose", "malvinas argentinas sur"],
    "avellaneda": ["avellaneda", "dock sud", "pineyro", "wilde", "sarandi", "villa dominico", "crucecita", "villa corina",
                   "gerli", "barracas al sur", "ciudad evita sur"],
    "berazategui": ["berazategui", "hudson", "guillermo enrique hudson", "ranelagh", "sourigues", "carlos tomas sourigues",
                    "pereyra", "platanos", "villa espana", "el pato", "juan maria gutierrez", "gutierrez"],
    "esteban echeverria": ["esteban echeverria", "monte grande", "luis guillon", "el jaguel", "9 de abril", "nueve de abril",
                           "villa fox", "canning"],
    "ezeiza": ["ezeiza", "tristan suarez", "carlos spegazzini", "spegazzini", "la union", "aeropuerto internacional ezeiza"],
    "florencio varela": ["florencio varela", "bosques", "villa vatteone", "zeballos", "ingeniero juan allan", "ingeniero allan",
                         "allan", "villa san luis", "gobernador costa", "santa rosa", "la capilla", "villa mónica", "villa monica"],
    "hurlingham": ["hurlingham", "villa tesei", "william c morris", "william morris"],
    "ituzaingo": ["ituzaingo", "villa udaondo", "udaondo", "parque leloir", "leloir"],
    "jose c paz": ["jose c paz", "jose c. paz"],
    "la matanza": ["la matanza", "san justo", "ramos mejia", "lomas del mirador", "villa luzuriaga", "isidro casanova",
                   "gonzalez catan", "gregorio de laferrere", "laferrere", "virrey del pino", "ciudad evita", "aldo bonzi",
                   "la tablada", "tapiales", "villa madero", "san alberto", "rafael castillo", "20 de junio", "veinte de junio",
                   "ciudad madero", "villa celina", "villa insuperable", "lomas de zamora oeste"],
    "lanus": ["lanus", "lanus este", "lanus oeste", "remedios de escalada", "escalada", "valentin alsina", "monte chingolo",
              "villa diamante", "villa caraza", "jose hernandez", "ciudad de lanus"],
    "lomas de zamora": ["lomas de zamora", "banfield", "temperley", "turdera", "llavallol", "ingeniero budge", "villa fiorito",
                        "villa albertini", "parque baron", "villa centenario", "santa catalina", "san jose lomas"],
    "malvinas argentinas": ["malvinas argentinas", "los polvorines", "polvorines", "grand bourg", "tortuguitas", "pablo nogues",
                            "ingeniero pablo nogues", "villa de mayo", "ingeniero adolfo sourdeaux", "sourdeaux", "tierras altas"],
    "merlo": ["merlo", "libertad", "mariano acosta", "san antonio de padua", "padua", "parque san martin", "pontevedra", "balbin"],
    "moreno": ["moreno", "paso del rey", "francisco alvarez", "la reja", "trujui", "cuartel v", "cuartel quinto", "general rodriguez sur"],
    "moron": ["moron", "castelar", "haedo", "villa sarmiento", "el palomar", "palomar"],
    "quilmes": ["quilmes", "quilmes oeste", "quilmes este", "bernal", "bernal este", "bernal oeste", "don bosco", "ezpeleta",
                "ezpeleta este", "ezpeleta oeste", "san francisco solano", "solano", "villa la florida", "la florida quilmes",
                "villa de mayo quilmes"],
    "san fernando": ["san fernando", "victoria", "virreyes", "virreyes este", "virreyes oeste", "carupa"],
    "san isidro": ["san isidro", "boulogne", "boulogne sur mer", "beccar", "martinez", "acassuso", "villa adelina", "la lucila del mar",
                   "villa la nata"],
    "san martin": ["san martin", "villa ballester", "villa lynch", "jose leon suarez", "billinghurst", "villa maipu", "san andres",
                   "villa libertad", "villa zagala", "chilavert", "villa general jose tomas guido", "villa granaderos de san martin"],
    "san miguel": ["san miguel", "bella vista", "muniz", "santa maria", "campo de mayo", "barrufaldi"],
    "tigre": ["tigre", "general pacheco", "don torcuato", "el talar", "benavidez", "ricardo rojas", "troncos del talar", "dique lujan",
              "rincon de milberg", "villa la ñata", "las tunas", "pacheco"],
    "tres de febrero": ["tres de febrero", "caseros", "ciudadela", "santos lugares", "martin coronado", "villa bosch", "loma hermosa",
                        "pablo podesta", "saenz pena", "ciudad jardin", "ciudad jardin lomas del palomar", "el libertador",
                        "villa raffo", "11 de septiembre", "once de septiembre", "jose ingenieros", "remedios de escalada de san martin"],
    "vicente lopez": ["vicente lopez", "olivos", "florida", "florida oeste", "florida este", "munro", "villa martelli", "la lucila",
                      "carapachay", "villa adelina vicente lopez"],
    "san vicente": ["san vicente", "alejandro korn", "domselaar"],
    "canuelas": ["canuelas", "uribelarrea", "maximo paz"],
    "la plata": ["la plata", "city bell", "gonnet", "manuel b gonnet", "ringuelet", "tolosa", "los hornos", "melchor romero", "villa elisa",
                 "san carlos", "villa elvira", "altos de san lorenzo", "abasto", "arturo segui", "etcheverry", "olmos", "lisandro olmos",
                 "joaquin gorina", "gorina", "villa garibaldi", "san lorenzo", "hernandez", "romero"],
    "berisso": ["berisso", "villa zula", "los talas"],
    "ensenada": ["ensenada", "punta lara", "isla santiago"],
    "escobar": ["escobar", "belen de escobar", "matheu", "loma verde", "maquinista savio", "ingeniero maschwitz"],
    "garin": ["garin"],
    "ingeniero maschwitz": ["ingeniero maschwitz", "maschwitz"],
    "pilar": ["pilar", "manzanares", "fatima", "manuel alberti", "champagnat", "villa astolfi", "zelaya", "presidente derqui sur", "pilar centro"],
    "del viso": ["del viso"],
    "derqui": ["derqui", "presidente derqui"],
    "villa rosa": ["villa rosa"],
    "nordelta": ["nordelta"],
    "lujan": ["lujan", "jauregui", "open door", "carlos keen"],
    "general rodriguez": ["general rodriguez"],
    "campana": ["campana"],
    "zarate": ["zarate", "lima"],
}

_FAMILIA_POR_LOCALIDAD = {}
for _familia, _lista in _LOCALIDADES.items():
    for _loc in _lista:
        _FAMILIA_POR_LOCALIDAD.setdefault(normalizar(_loc), _familia)

# Centro aproximado de cada familia de zona (lat, lon) — solo para localidades que no están en la lista de arriba.
_CENTROS = {
    "caba": (-34.6037, -58.4400), "almirante brown": (-34.8000, -58.3900), "avellaneda": (-34.6600, -58.3600),
    "berazategui": (-34.7600, -58.2100), "esteban echeverria": (-34.8200, -58.4700), "ezeiza": (-34.8600, -58.5200),
    "florencio varela": (-34.8200, -58.2800), "hurlingham": (-34.6000, -58.6400), "ituzaingo": (-34.6600, -58.6700),
    "jose c paz": (-34.5200, -58.7600), "la matanza": (-34.7500, -58.5600), "lanus": (-34.7000, -58.3900),
    "lomas de zamora": (-34.7700, -58.4000), "malvinas argentinas": (-34.5000, -58.6900), "merlo": (-34.6700, -58.7300),
    "moreno": (-34.6400, -58.7900), "moron": (-34.6500, -58.6200), "quilmes": (-34.7300, -58.2600),
    "san fernando": (-34.4400, -58.5600), "san isidro": (-34.4800, -58.5200), "san martin": (-34.5700, -58.5400),
    "san miguel": (-34.5400, -58.7100), "tigre": (-34.4200, -58.5800), "tres de febrero": (-34.6000, -58.5700),
    "vicente lopez": (-34.5200, -58.4800), "san vicente": (-35.0200, -58.4200), "canuelas": (-35.0500, -58.7600),
    "la plata": (-34.9200, -57.9500), "berisso": (-34.8700, -57.8800), "ensenada": (-34.8600, -57.9100),
    "escobar": (-34.3500, -58.7900), "garin": (-34.4200, -58.7500), "ingeniero maschwitz": (-34.3800, -58.7400),
    "pilar": (-34.4600, -58.9100), "del viso": (-34.4600, -58.8000), "derqui": (-34.4900, -58.8500),
    "villa rosa": (-34.4400, -58.8900), "nordelta": (-34.4000, -58.6500), "lujan": (-34.5700, -59.1100),
    "general rodriguez": (-34.6100, -58.9500), "campana": (-34.1600, -58.9600), "zarate": (-34.1000, -59.0300),
}


def _distancia_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _quitar_orientacion(nombre):
    return re.sub(r"\s+(este|oeste|norte|sur|centro)$", "", nombre)


def familia_de_destino(provincia, localidad, lat=None, lon=None):
    """Familia de zona de un destino (ver familia_de_zona), o None si no se puede ubicar."""
    if normalizar(provincia) in ("capital federal", "caba", "ciudad autonoma de buenos aires"):
        return "caba"
    nombre = normalizar(localidad)
    for candidato in (nombre, _quitar_orientacion(nombre)):
        if candidato in _FAMILIA_POR_LOCALIDAD:
            return _FAMILIA_POR_LOCALIDAD[candidato]
    if lat is not None and lon is not None:
        familia, d = min(((f, _distancia_km(lat, lon, c[0], c[1])) for f, c in _CENTROS.items() if f != "caba"), key=lambda x: x[1])
        if d <= MAX_KM_FALLBACK:
            return familia
    return None

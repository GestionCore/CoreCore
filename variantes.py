"""
Variantes por atributos (Fase 2 del pivot multi-rubro, docs/PIVOT_SAAS.md): qué distingue a una publicación de otra de su mismo modelo, SIN leer el título.

Antes el talle salía de un patrón sobre el título («un número al final es un talle»): «Apple iPhone 15» quedaba con talle «15» y el mismo modelo que el «Apple iPhone 14». Ahora la variante
sale de los atributos que informa Mercado Libre, que son datos y no una suposición. Qué se verificó contra Mercado Libre real (docs/SONDEO_FASE0.md):
  · Una publicación con VARIACIONES clásicas trae en cada una `attribute_combinations` (color, talle…): esos son, por definición, sus atributos de variante.
  · Una publicación sin variaciones (el modelo nuevo: cada color y cada talle es su propia publicación, agrupadas por `family_id`) trae todos sus atributos. Los que definen la variante son
    (a) los que la categoría marca `allow_variations` (COLOR, SIZE…) y (b) los que CAMBIAN entre las publicaciones de su familia, aunque la categoría no los marque: la memoria interna
    de un celular, los litros de una pintura, la capacidad de un disco. Nunca los datos técnicos (peso del paquete, GTIN, SKU) ni los que Mercado Libre marca `hidden`.
  · Un valor «Único» no es un dato: no distingue nada.
Sin nada que distinga, la etiqueta es «Única». Las columnas viejas `talle` y `color` se siguen llenando, pero desde los atributos y nunca desde el título.
"""
import unicodedata

ID_TALLE = "SIZE"
ID_COLOR = "COLOR"

# Datos técnicos o repetidos que NUNCA son una variante ni valen la pena guardar (aunque la categoría no los marque ocultos).
TECNICOS = frozenset({
    "GTIN", "EMPTY_GTIN_REASON", "AGID", "MPN", "SELLER_SKU", "ITEM_CONDITION", "PACKAGE_DATA_SOURCE", "MAIN_COLOR",       # MAIN_COLOR repite a COLOR con otro nombre
})
PREFIJOS_TECNICOS = ("PACKAGE_", "SELLER_PACKAGE_", "FILTRABLE_", "SIZE_GRID", "IS_", "HAS_", "WITH_")
# Identifican al PRODUCTO (todos los de una familia los comparten): se guardan, pero no distinguen una variante de otra.
IDENTIFICAN_PRODUCTO = frozenset({"BRAND", "MODEL", "LINE", "DETAILED_MODEL"})

_SIN_DATO = {"unico", "unica", "talle unico", "no aplica", "n/a", "sin especificar", "sin definir", "no especificado"}


def _sin_acentos(texto):
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().strip().lower()


def es_valor_util(valor):
    """Un valor que distingue algo: no vacío ni “Único”, “N/A”… (cada vendedor lo escribe a su manera)."""
    return valor is not None and str(valor).strip() != "" and _sin_acentos(valor) not in _SIN_DATO


def es_tecnico(id_atributo):
    return id_atributo in TECNICOS or str(id_atributo).startswith(PREFIJOS_TECNICOS)


def _limpio(atributo):
    """Del atributo de Mercado Libre, solo lo que sirve: id, nombre y valor (con su id y, si es un número con unidad, la estructura)."""
    salida = {"id": atributo.get("id"), "name": atributo.get("name"), "value_id": atributo.get("value_id"), "value_name": str(atributo.get("value_name")).strip()}
    if atributo.get("value_struct"):
        salida["value_struct"] = atributo["value_struct"]
    return {k: v for k, v in salida.items() if v is not None}


def atributos_visibles(atributos_item, ocultos=()):
    """{id: atributo limpio} de los atributos de una publicación con un valor útil, sin los técnicos ni los que la categoría marca ocultos."""
    ocultos = set(ocultos or ())
    visibles = {}
    for a in atributos_item or []:
        id_atributo = a.get("id")
        if not id_atributo or id_atributo in ocultos or es_tecnico(id_atributo) or not es_valor_util(a.get("value_name")):
            continue
        visibles[id_atributo] = _limpio(a)
    return visibles


def mapa_clave(atributos_item, ocultos=()):
    """{id: valor} compacto de los atributos visibles de una publicación (lo que se guarda en productos_padre.atributos_clave: marca, modelo, color, memoria…)."""
    return {id_atributo: a["value_name"] for id_atributo, a in atributos_visibles(atributos_item, ocultos).items()}


def atributos_que_cambian(mapas):
    """
    Los ids de atributo que toman al menos dos valores distintos entre los `mapas` (los atributos de las publicaciones de una misma familia). Los que identifican al producto
    (marca, modelo) no cuentan: si cambian es otro producto, no otra variante.
    """
    valores = {}
    for mapa in mapas or []:
        for id_atributo, valor in (mapa or {}).items():
            valores.setdefault(id_atributo, set()).add(_sin_acentos(valor))
    return {i for i, v in valores.items() if len(v) >= 2 and i not in IDENTIFICAN_PRODUCTO and not es_tecnico(i)}


def atributos_distintivos(mapas, dimensiones=()):
    """
    Los ids de atributo que alcanzan para distinguir entre sí a las publicaciones de una familia (`mapas`: los `mapa_clave` de todas), sin ensuciar la etiqueta con lo que no hace falta.
    Entran siempre los que la categoría marca como variación (`dimensiones`) y cambian entre ellas (el color, el talle); los demás que también cambian (la memoria de un celular, los
    litros de una pintura, la composición de una tela) solo si con lo anterior dos publicaciones siguen pareciendo iguales, y solo si de verdad las separan.
    """
    cambian = atributos_que_cambian(mapas)
    if not cambian:
        return []
    elegidos = [i for i in cambian if i in dimensiones]

    def distintas(ids):
        return len({tuple(m.get(i) for i in ids) for m in mapas})
    for i in sorted((i for i in cambian if i not in elegidos), key=lambda i: _orden(i, dimensiones)):
        if distintas(elegidos) == len(mapas):
            break
        if distintas(elegidos + [i]) > distintas(elegidos):
            elegidos.append(i)
    return sorted(elegidos, key=lambda i: _orden(i, dimensiones))


def _orden(id_atributo, dimensiones):
    """Primero lo que mide o cuenta (memoria, litros, talle), el color al final: «128 GB / Azul», «4 L / Blanco», «M / Negro»."""
    posicion = list(dimensiones).index(id_atributo) if id_atributo in dimensiones else 1000
    return (id_atributo == ID_COLOR, posicion, id_atributo)


def atributos_de_variante(atributos_item, combinaciones=None, dimensiones=(), distintivos=None, ocultos=()):
    """
    La lista de atributos que definen la variante de una publicación (o de una variación suya). `combinaciones` son las `attribute_combinations` de una variación clásica: si hay,
    esas son la variante. Si no: los `distintivos` de su familia (`atributos_distintivos`: lo que de verdad la separa de sus hermanas; lo que es igual en todas —el diseño de la tela
    de una familia entera— no aporta); sin familia o sin nada que cambie, los que la categoría marca `allow_variations` (`dimensiones`).
    """
    if combinaciones:
        propias = [_limpio(c) for c in combinaciones if c.get("id") and es_valor_util(c.get("value_name"))]
        return sorted(propias, key=lambda a: _orden(a["id"], dimensiones))
    candidatos = set(distintivos) if distintivos else set(dimensiones)
    visibles = atributos_visibles(atributos_item, ocultos)
    elegidos = [a for i, a in visibles.items() if i in candidatos and i not in IDENTIFICAN_PRODUCTO]
    return sorted(elegidos, key=lambda a: _orden(a["id"], dimensiones))


def etiqueta_de(atributos):
    """El texto que se muestra: los valores unidos con « / » («128 GB / Azul»); «Única» si la publicación no tiene nada que la distinga."""
    vistos, partes = set(), []
    for a in atributos or []:
        valor = str(a.get("value_name") or "").strip()
        if valor and _sin_acentos(valor) not in vistos:
            vistos.add(_sin_acentos(valor))
            partes.append(valor)
    return " / ".join(partes) or "Única"


def _valor_de(id_atributo, nombres, atributos_item, combinaciones):
    for c in combinaciones or []:
        if (c.get("id") == id_atributo or c.get("name") in nombres) and es_valor_util(c.get("value_name")):
            return str(c["value_name"]).strip()
    for a in atributos_item or []:
        if a.get("id") == id_atributo and es_valor_util(a.get("value_name")):
            return str(a["value_name"]).strip()
    return None


def talle_y_color(atributos_item, combinaciones=None):
    """
    Las columnas viejas `talle` y `color` de productos_variantes, mientras los lectores migran a `atributos`/`etiqueta`. El talle es el atributo SIZE (de la variación o de la publicación)
    en mayúsculas, el color el atributo COLOR; sin dato, «Único». NUNCA se deduce del título.
    """
    talle = _valor_de(ID_TALLE, ("Talle", "Size"), atributos_item, combinaciones)
    color = _valor_de(ID_COLOR, ("Color",), atributos_item, combinaciones)
    return (talle.upper() if talle else "Único"), (color or "Único")

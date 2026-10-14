"""
Mercado — lo que Mercado Libre muestra de cada categoría, leído de las tablas globales que llena el relevador (`mercado_*`, ver mercado_relevador.py).

Solo lee la base: sin llamadas a Mercado Libre ni token, así que la pantalla abre rápido y sirve a cualquier rubro. Nada se inventa: Mercado Libre informa la POSICIÓN de cada búsqueda
(no cuántas veces se busca), el tamaño de la oferta y, de los productos de catálogo, los precios; NO informa cuánto vende cada competidor. Por eso acá hay ranking, rachas, oferta y
precios de la muestra —siempre con cuánto se midió—, y donde no hay dato (una categoría casi sin catálogo, o menos de dos días de historia) se dice «sin dato», nunca un cero.
"""
import re
import unicodedata
from datetime import timedelta

SITIO = "MLA"                                       # la lista general de Mercado Libre (no es una categoría real)
DIAS_NUEVA = 7                                      # una búsqueda que entró hace menos de esto es «nueva esta semana»
HHI_MEDIA, HHI_ALTA = 1500, 2500                    # umbrales habituales de concentración (HHI de 0 a 10.000)

_STOP = {"de", "para", "con", "el", "la", "los", "las", "un", "una", "y", "en", "por", "del", "al", "a"}
# Palabras que no distinguen un producto de otro (para saber si una búsqueda «es» de una publicación): «mujer» o «premium» están en medio catálogo
_GENERICAS = {"hombre", "hombres", "mujer", "mujeres", "unisex", "nino", "nina", "ninos", "ninas", "kit", "set", "combo", "pack", "premium", "original", "nuevo", "nueva", "oferta",
              "barato", "baratos", "barata", "baratas", "importado", "importada", "envio", "gratis"}


def _normalizar(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", (texto or "").lower()) if not unicodedata.combining(c))


def tokens_de(texto):
    """Las palabras que distinguen a un texto (sin acentos, sin conectores, en singular a lo bruto: «camperas» → «campera»)."""
    tokens = set()
    for palabra in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        if palabra in _STOP:
            continue
        tokens.add(re.sub(r"(es|s)$", "", palabra) if len(palabra) > 4 else palabra)
    return tokens


def _tokens_que_distinguen(busqueda):
    return {t for t in tokens_de(busqueda) if t not in _GENERICAS and re.sub(r"(es|s)$", "", t) not in _GENERICAS and len(t) >= 3}


def publicaciones_con_busqueda(busqueda, titulos_tokenizados):
    """Cuántas publicaciones propias tienen TODAS las palabras que distinguen a esa búsqueda en su título. Una búsqueda solo de palabras genéricas («mujer») no coincide con ninguna."""
    clave = _tokens_que_distinguen(busqueda)
    if not clave:
        return 0
    return sum(1 for tokens in titulos_tokenizados if clave <= tokens)


# ── Lectura de las tablas ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def cobertura(cursor):
    """Qué se mide y desde cuándo: la historia disponible y la última actualización. Es lo primero que se muestra: sin saber cuánto vemos, ningún número vale."""
    cursor.execute("SELECT min(fecha), max(fecha), count(DISTINCT fecha) FROM mercado_tendencias_diaria")
    desde, hasta, dias = cursor.fetchone()
    cursor.execute("SELECT count(*) FROM mercado_categorias WHERE seguida AND category_id <> %s", (SITIO,))
    return {"desde": desde, "hasta": hasta, "dias": dias or 0, "categorias": cursor.fetchone()[0]}


def categorias_de_la_cuenta(cursor, cuenta_id):
    """[{category_id, nombre, camino, activas, publicaciones, relevada}] de las categorías donde la cuenta tiene publicaciones activas, la de más publicaciones primero."""
    cursor.execute(
        """SELECT p.category_id, count(*) AS activas, c.nombre, c.camino_nombres, c.publicaciones, c.dominio_id
           FROM productos_padre p LEFT JOIN mercado_categorias c ON c.category_id = p.category_id
           WHERE p.cuenta_id = %s AND p.estado = 'active' AND p.category_id IS NOT NULL
           GROUP BY p.category_id, c.nombre, c.camino_nombres, c.publicaciones, c.dominio_id
           ORDER BY activas DESC, p.category_id""",
        (cuenta_id,),
    )
    return [{"category_id": i, "nombre": nombre or i, "camino": camino or [], "activas": activas, "publicaciones": publicaciones, "dominio_id": dominio, "relevada": nombre is not None}
            for i, activas, nombre, camino, publicaciones, dominio in cursor.fetchall()]


def titulos_de_la_cuenta(cursor, cuenta_id):
    cursor.execute("SELECT titulo FROM productos_padre WHERE cuenta_id = %s AND estado = 'active' AND titulo IS NOT NULL", (cuenta_id,))
    return [tokens_de(t) for (t,) in cursor.fetchall()]


def categorias_seguidas(cursor):
    """Todas las categorías que se relevan, con lo último que se sabe de cada una (para el selector y la tabla de comparación)."""
    cursor.execute(
        """SELECT c.category_id, c.nombre, c.camino_nombres, c.es_hoja, c.publicaciones, m.precio_p50, m.pct_full, m.pct_envio_gratis, m.hhi, m.muestra_ofertas,
                  (SELECT count(*) FROM mercado_keyword_estado e WHERE e.category_id = c.category_id AND e.posicion_actual IS NOT NULL)
           FROM mercado_categorias c
           LEFT JOIN LATERAL (SELECT precio_p50, pct_full, pct_envio_gratis, hhi, muestra_ofertas FROM mercado_categoria_diaria d
                              WHERE d.category_id = c.category_id AND d.muestra_ofertas > 0 ORDER BY fecha DESC LIMIT 1) m ON true
           WHERE c.seguida AND c.category_id <> %s
           ORDER BY c.publicaciones DESC NULLS LAST, c.nombre""",
        (SITIO,),
    )
    columnas = ("category_id", "nombre", "camino", "es_hoja", "publicaciones", "precio_p50", "pct_full", "pct_envio_gratis", "hhi", "muestra_ofertas", "busquedas")
    filas = []
    for fila in cursor.fetchall():
        d = dict(zip(columnas, fila))
        d["camino"] = d["camino"] or []
        d["concentracion"] = etiqueta_concentracion(d["hhi"])
        filas.append(d)
    return filas


def etiqueta_concentracion(hhi):
    """(nivel, texto) de qué tan repartida está la oferta de la muestra; None si no hay muestra. Mucha concentración = pocos vendedores dominan."""
    if hhi is None:
        return None
    if hhi >= HHI_ALTA:
        return ("alta", "Concentrada: pocos vendedores dominan")
    if hhi >= HHI_MEDIA:
        return ("media", "Algo concentrada")
    return ("baja", "Repartida entre muchos vendedores")


def _variacion(serie, dias):
    """(diferencia, porcentaje) de las publicaciones contra el dato más reciente que tenga al menos `dias` de antigüedad; None si la historia todavía no llega. `serie`: [(fecha, valor)] de la más nueva a la más vieja."""
    if len(serie) < 2:
        return None
    fecha_hoy, valor_hoy = serie[0]
    limite = fecha_hoy - timedelta(days=dias)
    for fecha, valor in serie[1:]:
        if fecha <= limite:
            if not valor:
                return None
            return {"diferencia": valor_hoy - valor, "pct": round((valor_hoy - valor) / valor * 100, 1), "desde": fecha}
    return None


def ficha_categoria(cursor, category_id):
    """Todo lo que se sabe de UNA categoría (tamaño de la oferta y su evolución, precios de la muestra, logística, concentración, peso en su rubro). None si no se releva."""
    cursor.execute(
        "SELECT category_id, nombre, camino, camino_nombres, dominio_id, es_hoja, publicaciones FROM mercado_categorias WHERE category_id = %s", (category_id,))
    fila = cursor.fetchone()
    if not fila:
        return None
    ficha = dict(zip(("category_id", "nombre", "camino", "camino_nombres", "dominio_id", "es_hoja", "publicaciones"), fila))
    cursor.execute("SELECT fecha, publicaciones FROM mercado_categoria_diaria WHERE category_id = %s AND publicaciones IS NOT NULL ORDER BY fecha DESC LIMIT 400", (category_id,))
    serie = cursor.fetchall()
    ficha["dias_con_dato"] = len(serie)
    ficha["variacion_7"], ficha["variacion_30"] = _variacion(serie, 7), _variacion(serie, 30)
    ficha["serie"] = list(reversed(serie[:60]))

    # Peso en su rubro: su tamaño contra el de la categoría raíz (el primer id de su camino)
    ficha["peso_rubro"] = None
    camino = ficha["camino"] or []
    raiz = camino[0] if camino else None
    if raiz and raiz != category_id and ficha["publicaciones"]:
        cursor.execute("SELECT nombre, publicaciones FROM mercado_categorias WHERE category_id = %s", (raiz,))
        fila_raiz = cursor.fetchone()
        if fila_raiz and fila_raiz[1]:
            ficha["peso_rubro"] = {"nombre": fila_raiz[0], "pct": round(ficha["publicaciones"] / fila_raiz[1] * 100, 2)}

    cursor.execute(
        """SELECT fecha, muestra_productos, muestra_ofertas, muestra_vendedores, precio_min, precio_p25, precio_p50, precio_p75, precio_max, pct_full, pct_envio_gratis, pct_tienda_oficial,
                  pct_con_descuento, descuento_promedio, concentracion_top3, hhi, muestra_alcance
           FROM mercado_categoria_diaria WHERE category_id = %s AND muestra_ofertas IS NOT NULL ORDER BY fecha DESC LIMIT 1""", (category_id,))
    m = cursor.fetchone()
    ficha["muestra"] = None
    if m:
        ficha["muestra"] = dict(zip(("fecha", "productos", "ofertas", "vendedores", "precio_min", "precio_p25", "precio_p50", "precio_p75", "precio_max", "pct_full", "pct_envio_gratis",
                                     "pct_tienda_oficial", "pct_con_descuento", "descuento_promedio", "concentracion_top3", "hhi", "alcance"), m))
        ficha["muestra"]["concentracion"] = etiqueta_concentracion(ficha["muestra"]["hhi"])
        ficha["muestra"]["vacia"] = not ficha["muestra"]["ofertas"]
    return ficha


def estado_busqueda(posicion, posicion_hace_7d, primera_vez, ultima_fecha_lista, primera_fecha_lista):
    """
    (clave, texto) del movimiento de una búsqueda, o None si todavía no se puede decir nada. Una búsqueda que ya estaba cuando se empezó a medir no puede llamarse «nueva»: no se sabe desde cuándo está.
    """
    if posicion_hace_7d is not None:
        cambio = posicion_hace_7d - posicion
        if cambio > 0:
            return ("sube", f"Subió {cambio} {'puesto' if cambio == 1 else 'puestos'} en la semana")
        if cambio < 0:
            return ("baja", f"Bajó {-cambio} {'puesto' if cambio == -1 else 'puestos'} en la semana")
        return ("igual", "Mismo puesto que hace una semana")
    if primera_fecha_lista and primera_vez and primera_vez > primera_fecha_lista and (ultima_fecha_lista - primera_vez).days < DIAS_NUEVA:
        return ("nueva", "Entró esta semana")
    return None


def busquedas_en_alza(cursor, category_id, limite=30):
    """Las búsquedas en alza de una categoría (o de todo Mercado Libre con `MLA`), con su puesto, movimiento, racha y lo que Mercado Libre entiende de ellas."""
    cursor.execute("SELECT min(fecha), max(fecha) FROM mercado_tendencias_diaria WHERE category_id = %s", (category_id,))
    primera, ultima = cursor.fetchone()
    cursor.execute(
        """SELECT k.id, k.texto, e.posicion_actual, e.posicion_hace_7d, e.racha_dias, e.dias_en_lista, e.mejor_posicion, e.primera_vez, k.categoria_id, k.dominio_id, k.atributos
           FROM mercado_keyword_estado e JOIN mercado_keywords k ON k.id = e.keyword_id
           WHERE e.category_id = %s AND e.posicion_actual IS NOT NULL ORDER BY e.posicion_actual, k.texto LIMIT %s""",
        (category_id, limite),
    )
    filas = []
    for kid, texto, posicion, hace_7d, racha, dias_en_lista, mejor, primera_vez, categoria_id, dominio_id, atributos in cursor.fetchall():
        estado = estado_busqueda(posicion, hace_7d, primera_vez, ultima, primera) if ultima else None
        filas.append({
            "id": kid, "texto": texto, "posicion": posicion, "movimiento": estado, "racha": racha if racha and racha >= 3 else None, "dias_en_lista": dias_en_lista,
            "mejor_posicion": mejor, "category_id_busqueda": categoria_id, "dominio_id": dominio_id, "category_id": category_id,
            "entiende": _entiende(atributos),
        })
    return filas


def _entiende(atributos):
    """Lo que Mercado Libre extrajo de la búsqueda («adidas · Mujer»): solo los valores, sin datos técnicos."""
    valores = []
    for a in atributos or []:
        valor = (a or {}).get("value_name")
        if valor and valor not in valores and str(valor).lower() not in ("estándar", "estandar", "no"):
            valores.append(str(valor))
    return valores[:3]


def busquedas_de_tus_categorias(cursor, categorias, titulos_tokenizados, por_categoria=8, maximo=30):
    """
    Las búsquedas en alza de TODAS las categorías de la cuenta, mezcladas por puesto, con una marca de si ya tiene publicaciones con esa búsqueda. Solo categorías ya relevadas.
    """
    filas = []
    for categoria in categorias:
        if not categoria["relevada"]:
            continue
        for fila in busquedas_en_alza(cursor, categoria["category_id"], limite=por_categoria):
            fila["categoria_nombre"] = categoria["nombre"]
            fila["tus_publicaciones"] = publicaciones_con_busqueda(fila["texto"], titulos_tokenizados)
            filas.append(fila)
    filas.sort(key=lambda f: (f["posicion"], f["categoria_nombre"], f["texto"]))
    return filas[:maximo]


_ID_CATEGORIA = re.compile(r"^MLA[0-9]*$")


def armar_pantalla(cursor, cuenta_id, categoria_pedida=None):
    """Todo lo que necesita la plantilla de /mercado en una sola pasada (unas diez consultas a la base, ninguna a Mercado Libre)."""
    datos = {"cobertura": cobertura(cursor)}
    propias = categorias_de_la_cuenta(cursor, cuenta_id)
    titulos = titulos_de_la_cuenta(cursor, cuenta_id)
    seguidas = categorias_seguidas(cursor)
    datos.update(propias=propias, seguidas=seguidas)
    datos["busquedas_tuyas"] = busquedas_de_tus_categorias(cursor, propias, titulos)
    datos["sin_relevar"] = [c for c in propias if not c["relevada"]]

    # La categoría de la ficha: la que pidió la persona (si se releva), si no la de la cuenta con más publicaciones, si no la raíz más grande
    ids_seguidas = {c["category_id"] for c in seguidas}
    elegida = categoria_pedida if categoria_pedida and _ID_CATEGORIA.match(categoria_pedida) and categoria_pedida in ids_seguidas else None
    if not elegida:
        elegida = next((c["category_id"] for c in propias if c["category_id"] in ids_seguidas), None) or (seguidas[0]["category_id"] if seguidas else None)
    datos["elegida"] = elegida
    datos["ficha"] = ficha_categoria(cursor, elegida) if elegida else None
    datos["busquedas_ficha"] = []
    if elegida:
        datos["busquedas_ficha"] = busquedas_en_alza(cursor, elegida, limite=20)
        for fila in datos["busquedas_ficha"]:
            fila["tus_publicaciones"] = publicaciones_con_busqueda(fila["texto"], titulos)
    datos["ids_propias"] = {c["category_id"] for c in propias}
    return datos

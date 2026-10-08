"""
Tendencias — portado de Santi Mens.

Bug de fuga entre cuentas encontrado (mismo patrón que ads.py,
facturacion.py y logistica.py): `_categoria_cache` era un único slot
global — la categoría de la PRIMERA cuenta que consultara (ej:
"Ropa y Accesorios") quedaba fija para todas las demás cuentas,
aunque vendieran otra cosa completamente distinta. Ahora se cachea
por cuenta_id.

También: tendencias_historial ahora tiene cuenta_id en su clave (según
el esquema multi-tenant), y el "INSERT OR IGNORE" de SQLite se
resuelve con "ON CONFLICT DO NOTHING" en Postgres.
"""
import re
import threading
import cache_db
import meli_http
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from utils import hoy_argentina, plural

# Palabras que no distinguen un producto de otro en ningún rubro (para comparar títulos entre sí)
PALABRAS_GENERICAS = {
    "de", "para", "con", "sin", "talle", "premium", "clasica", "clásica", "original", "nuevo", "nueva", "excelente", "excelent",
    "calidad", "super", "súper", "grande", "chico", "especial", "oferta", "importado", "envio", "envío", "gratis", "pack", "combo",
    "hombre", "mujer", "unisex", "niño", "niña", "kit", "set",
}
PALABRAS_RELLENO_TITULO = {"de", "para", "con", "el", "la", "los", "las", "un", "una", "y", "en"}

_categoria_cache = {}


def limpiar_titulo_modelo_local(titulo):
    # productos_padre.titulo es nullable (puede quedar NULL si una
    # sincronización se interrumpió a mitad de camino) — sin este guard,
    # cualquier función de acá abajo que reciba un producto con título
    # vacío tira un TypeError no capturado y tumba toda /tendencias.
    if not titulo:
        return ""
    t = re.sub(r'\b(talle|size)\s*[:#]?\s*(xxxl|xxl|xl|l|m|s|\d+)\b', '', titulo, flags=re.IGNORECASE)
    t = re.sub(r'\b(xxxl|xxl|xl|l|m|s)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+\d{1,2}\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def obtener_categoria_principal(access_token, cuenta_id, cursor, site_id="MLA"):
    if cuenta_id in _categoria_cache:
        return _categoria_cache[cuenta_id]["id"], _categoria_cache[cuenta_id]["nombre"]

    headers = {"Authorization": f"Bearer {access_token}"}
    cursor.execute("SELECT id_meli FROM productos_padre WHERE estado = 'active' LIMIT 1")
    fila = cursor.fetchone()
    if not fila:
        return None, None

    try:
        resp_item = meli_http.get(f"https://api.mercadolibre.com/items/{fila[0]}", headers=headers, timeout=8)
        if resp_item.status_code != 200:
            return None, None
        category_id = resp_item.json().get("category_id")
        if not category_id:
            return None, None

        resp_cat = meli_http.get(f"https://api.mercadolibre.com/categories/{category_id}", timeout=8)
        if resp_cat.status_code != 200:
            return category_id, None

        path = resp_cat.json().get("path_from_root", [])
        categoria_top = path[0] if path else {"id": category_id, "name": None}

        _categoria_cache[cuenta_id] = {"id": categoria_top.get("id"), "nombre": categoria_top.get("name")}
        return _categoria_cache[cuenta_id]["id"], _categoria_cache[cuenta_id]["nombre"]
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error detectando categoría: {e}")
        return None, None


_categoria_especifica_cache = {}   # cuenta_id -> (timestamp, (id, nombre))
TTL_CATEGORIA_ESPECIFICA_SEGUNDOS = 6 * 3600


def obtener_categoria_especifica(access_token, cuenta_id, cursor):
    """
    La categoría hoja más frecuente entre las publicaciones activas de la
    cuenta (ej: "Camperas y Tapados" en vez del rubro raíz "Ropa y
    Accesorios"). El rubro raíz sirve para el radar de MeLi, pero como
    referencia de competencia es tan amplio que no dice nada útil.
    Cacheada por cuenta_id (cada cuenta vende lo suyo).
    """
    ahora = datetime.now().timestamp()
    hit = _categoria_especifica_cache.get(cuenta_id)
    if hit and ahora - hit[0] < TTL_CATEGORIA_ESPECIFICA_SEGUNDOS:
        return hit[1]

    categorias = categorias_del_catalogo(cursor, 1)
    if not categorias:
        return None, None
    category_id = categorias[0][0]
    _, c = _get_json(f"https://api.mercadolibre.com/categories/{category_id}", {"Authorization": f"Bearer {access_token}"})
    resultado = (category_id, (c or {}).get("name"))
    if resultado[1]:
        _categoria_especifica_cache[cuenta_id] = (ahora, resultado)
    return resultado


def categorias_del_catalogo(cursor, maximo=3):
    """[(category_id, publicaciones activas)] de las categorías con más publicaciones de la cuenta. Sale de la base (el sync guarda category_id): sin llamadas a MeLi."""
    cursor.execute(
        "SELECT category_id, count(*) FROM productos_padre WHERE estado = 'active' AND category_id IS NOT NULL GROUP BY category_id ORDER BY 2 DESC, 1 LIMIT %s",
        (maximo,),
    )
    return [(fila[0], fila[1]) for fila in cursor.fetchall()]


TTL_TENDENCIAS_SEGUNDOS = 6 * 3600
CLAVE_TENDENCIAS = "tendencias_catalogo"


def mezclar_tendencias(listas_por_categoria):
    """
    Une las listas de tendencias de varias categorías de a una por turno (así cada categoría está representada arriba), sin repetir términos y
    renumerando la posición. `listas_por_categoria` es [(category_id, [tendencia, ...]), ...].
    """
    mezcla, vistos = [], set()
    largo = max((len(lista) for _, lista in listas_por_categoria), default=0)
    for i in range(largo):
        for cid, lista in listas_por_categoria:
            if i >= len(lista):
                continue
            kw = (lista[i].get("keyword") or "").strip().lower()
            if not kw or kw in vistos:
                continue
            vistos.add(kw)
            mezcla.append({**lista[i], "categoria_id": cid})
    for idx, tendencia in enumerate(mezcla):
        tendencia["relevante"] = True
        tendencia["posicion"] = idx + 1
        tendencia["es_top"] = idx < 20
    return mezcla


def obtener_tendencias_del_catalogo(access_token, cursor, cuenta_id, site_id="MLA", maximo_categorias=3):
    """
    Las tendencias de Mercado Libre de las categorías ESPECÍFICAS donde vende la cuenta (hoy: las 3 con más publicaciones activas). La categoría raíz
    ("Ropa y Accesorios") trae búsquedas ajenas al rubro ("slots casino", marcas que la cuenta no vende); las categorías hoja, no.
    Devuelve {"lista": [...], "categorias": [{"id", "nombre", "publicaciones"}]} o None si la cuenta todavía no tiene categorías (se usa la raíz).
    Cacheada 6 h por cuenta en la base: las tendencias de MeLi cambian por día y consultarlas en cada carga tardaba ~4 s.
    """
    categorias = categorias_del_catalogo(cursor, maximo_categorias)
    if not categorias:
        return None
    firma = ",".join(c for c, _ in categorias)
    hit, valor = cache_db.leer(cursor, cuenta_id, CLAVE_TENDENCIAS, firma, TTL_TENDENCIAS_SEGUNDOS, ttl_fallido=600)
    if hit and valor:
        return valor
    headers = {"Authorization": f"Bearer {access_token}"}
    listas, datos = [], []
    for cid, cantidad in categorias:
        lista = obtener_tendencias(access_token, site_id, category_id=cid)
        _, c = _get_json(f"https://api.mercadolibre.com/categories/{cid}", headers)
        listas.append((cid, lista))
        datos.append({"id": cid, "nombre": (c or {}).get("name") or cid, "publicaciones": cantidad})
    lista = mezclar_tendencias(listas)
    if not lista:
        cache_db.guardar(cursor, cuenta_id, CLAVE_TENDENCIAS, None, firma)       # MeLi no respondió: no se insiste en cada carga
        return None
    valor = {"lista": lista, "categorias": datos}
    cache_db.guardar(cursor, cuenta_id, CLAVE_TENDENCIAS, valor, firma)
    return valor


NOTA_LIMITE_DATOS = (
    "Mercado Libre dejó de publicar por API las ventas y visitas de otros vendedores, así que este análisis "
    "mide competencia y precios (la oferta pública en catálogo) — no la demanda real de un producto ajeno, "
    "que no se puede ver desde afuera. Para tus propios productos, tus ventas reales están en Ganancia Real."
)

_TIPOS_PUBLICACION = {
    "gold_pro": "Premium", "gold_premium": "Premium", "gold_special": "Clásica",
    "gold": "Oro", "silver": "Plata", "bronze": "Bronce", "free": "Gratuita",
}
_MEDALLAS_VENDEDOR = {"platinum": "MercadoLíder Platinum", "gold": "MercadoLíder Gold", "silver": "MercadoLíder"}
_NIVELES_REPUTACION = {"5_green": "Verde", "4_light_green": "Verde claro", "3_yellow": "Amarillo", "2_orange": "Naranja", "1_red": "Rojo"}


def _get_json(url, headers=None, params=None, timeout=10):
    """(status, json|None) — nunca levanta: un tropiezo de red o un 403 puntual no tumba el análisis entero."""
    try:
        resp = meli_http.get(url, headers=headers or {}, params=params, timeout=timeout)
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error de conexión con {url}: {e}")
        return None, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def _percentil(ordenados, p):
    if not ordenados:
        return None
    if len(ordenados) == 1:
        return ordenados[0]
    k = (len(ordenados) - 1) * p
    piso = int(k)
    techo = min(piso + 1, len(ordenados) - 1)
    return ordenados[piso] + (ordenados[techo] - ordenados[piso]) * (k - piso)


def _histograma_precios(precios, bandas=5):
    """5 bandas entre el percentil 5 y el 95 — un par de publicaciones carísimas (o regaladas) estiraban el eje y dejaban todo apilado en la primera banda."""
    if not precios:
        return []
    ordenados = sorted(precios)
    p_min, p_max = ordenados[0], ordenados[-1]
    if p_max == p_min:
        return [{"desde": round(p_min), "hasta": round(p_max), "cantidad": len(precios)}]
    lo, hi = _percentil(ordenados, 0.05), _percentil(ordenados, 0.95)
    if hi <= lo:
        lo, hi = p_min, p_max
    ancho = (hi - lo) / bandas
    cuentas = [0] * bandas
    for p in precios:
        idx = int((p - lo) / ancho) if ancho else 0
        cuentas[max(0, min(bandas - 1, idx))] += 1
    resultado = []
    for i in range(bandas):
        desde = p_min if i == 0 else lo + ancho * i
        hasta = p_max if i == bandas - 1 else lo + ancho * (i + 1)
        resultado.append({"desde": round(desde), "hasta": round(hasta), "cantidad": cuentas[i]})
    return resultado


def _info_categoria(headers, category_id):
    """Nombre, camino, total de publicaciones y tamaño relativo frente a sus categorías hermanas (mismo padre)."""
    _, c = _get_json(f"https://api.mercadolibre.com/categories/{category_id}", headers)
    if not c:
        return None
    path = c.get("path_from_root") or []
    info = {
        "id": c.get("id"), "nombre": c.get("name"), "camino": [p.get("name") for p in path],
        "total": c.get("total_items_in_this_category"), "hermanas": None, "share_rubro_pct": None,
    }
    if len(path) >= 2 and info["total"] is not None:
        _, padre = _get_json(f"https://api.mercadolibre.com/categories/{path[-2]['id']}", headers)
        if padre:
            hijos = padre.get("children_categories") or []
            # El total de la propia categoría y el que MeLi lista en su padre difieren (~15%):
            # se usa el del padre, que es el mismo que se ve al navegar el árbol y con el que
            # se comparan las hermanas — así el ranking y los números en pantalla coinciden.
            propio = next((h.get("total_items_in_this_category") for h in hijos if h.get("id") == info["id"]), None)
            if propio is not None:
                info["total"] = propio
            hijas = [h.get("total_items_in_this_category") or 0 for h in hijos]
            if hijas:
                info["hermanas"] = {
                    "posicion": sum(1 for t in hijas if t > info["total"]) + 1,
                    "de": len(hijas), "rubro_nombre": padre.get("name"),
                }
                total_padre = padre.get("total_items_in_this_category")
                if total_padre:
                    info["share_rubro_pct"] = round(info["total"] / total_padre * 100, 1)
    return info


_STOP_TOKENS = {"de", "para", "con", "el", "la", "los", "las", "un", "una", "y", "en", "por", "del", "al", "a"}
_cache_caminos_categoria = {}


def _normalizar(texto):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", (texto or "").lower()) if not unicodedata.combining(c))


def _tokens_relevantes(consulta):
    """Palabras que tiene que tener el nombre de un producto para considerarlo parte de la búsqueda (singularizadas a lo bruto: camperas -> campera)."""
    tokens = []
    for palabra in re.findall(r"[a-z0-9]+", _normalizar(consulta)):
        if palabra in _STOP_TOKENS:
            continue
        tokens.append(re.sub(r"(es|s)$", "", palabra) if len(palabra) > 4 else palabra)
    return tokens


def _candidatas_crudas(headers, consulta, site_id):
    _, data = _get_json(f"https://api.mercadolibre.com/sites/{site_id}/domain_discovery/search", headers, {"q": consulta, "limit": 4})
    return data if isinstance(data, list) else []


def _ids_camino(headers, category_id):
    """IDs de la categoría y todos sus ancestros — sirve para saber si una publicación cuelga (aunque sea de muy abajo) de la categoría analizada. Dato global de MeLi, cacheable sin scope por cuenta."""
    if category_id in _cache_caminos_categoria:
        return _cache_caminos_categoria[category_id]
    _, c = _get_json(f"https://api.mercadolibre.com/categories/{category_id}", headers)
    ids = {p.get("id") for p in (c or {}).get("path_from_root") or []} | {category_id} if c else {category_id}
    _cache_caminos_categoria[category_id] = ids
    return ids


def _detallar_candidatas(headers, crudas):
    """Cada categoría candidata de un término, con su cantidad real de publicaciones."""
    def _detalle(item):
        cid = item.get("category_id")
        _, c = _get_json(f"https://api.mercadolibre.com/categories/{cid}", headers)
        if not c:
            return {"id": cid, "nombre": item.get("category_name"), "camino": [], "total": None}
        return {
            "id": cid, "nombre": c.get("name"),
            "camino": [p.get("name") for p in (c.get("path_from_root") or [])],
            "total": c.get("total_items_in_this_category"),
        }

    con_id = [d for d in crudas if d.get("category_id")]
    if not con_id:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_detalle, con_id))


def _buscar_catalogo(headers, consulta, site_id, paginas):
    """(productos, error_estado) — varias páginas en paralelo: el filtro por dominio descarta buena parte de cada página."""
    def _pagina(offset):
        return _get_json(
            "https://api.mercadolibre.com/products/search", headers,
            {"q": consulta, "site_id": site_id, "status": "active", "limit": 50, "offset": offset}
        )
    with ThreadPoolExecutor(max_workers=min(paginas, 3)) as pool:
        resultados = list(pool.map(_pagina, [50 * i for i in range(paginas)]))
    primera_estado, primera = resultados[0]
    if primera is None:
        return None, primera_estado
    productos = []
    for _, data in resultados:
        productos.extend((data or {}).get("results") or [])
    return productos, None


def _publicaciones_de_producto(headers, product_id):
    st, data = _get_json(f"https://api.mercadolibre.com/products/{product_id}/items", headers, {"limit": 50})
    return (data or {}).get("results") or [] if st == 200 else []


def _perfil_vendedor(headers, seller_id):
    _, u = _get_json(f"https://api.mercadolibre.com/users/{seller_id}", headers)
    if not u:
        return {"id": seller_id, "nickname": f"Vendedor {seller_id}"}
    rep = u.get("seller_reputation") or {}
    return {
        "id": seller_id, "nickname": u.get("nickname") or f"Vendedor {seller_id}",
        "nivel": _NIVELES_REPUTACION.get(rep.get("level_id")),
        "medalla": _MEDALLAS_VENDEDOR.get(rep.get("power_seller_status")),
        "ventas_historicas": (rep.get("transactions") or {}).get("total"),
        "permalink": (u.get("permalink") or "").replace("http://", "https://") or None,
    }


def _pct(parte, total):
    return round(parte / total * 100, 1) if total else 0.0


def _armar_veredicto_mercado(total_categoria, hermanas, muestra_n, concentracion_top3_pct, iqr_relativo):
    """
    Traduce los números a texto plano — "¿cómo está la pelea acá?". Los
    umbrales son heurísticas declaradas, no una ciencia exacta: mejor
    ser honesto con eso que fingir una precisión que la muestra no
    tiene. No habla de "demanda" a propósito: esa cifra ya no se puede
    medir desde afuera (ver NOTA_LIMITE_DATOS).
    """
    contexto = None
    if hermanas and hermanas.get("de", 0) >= 3:
        contexto = f"{hermanas['posicion']}ª más poblada de {hermanas['de']} categorías de {hermanas['rubro_nombre']}"
    if total_categoria is not None:
        total_txt = f"{total_categoria:,}".replace(",", ".")
        if total_categoria >= 100000:
            comp_nivel, comp_texto = "alta", f"Categoría muy poblada — {total_txt} publicaciones activas"
        elif total_categoria >= 10000:
            comp_nivel, comp_texto = "media", f"Competencia media — {total_txt} publicaciones activas"
        else:
            comp_nivel, comp_texto = "baja", f"Categoría acotada — {total_txt} publicaciones activas"
    else:
        comp_nivel, comp_texto = None, "Tamaño de la categoría sin datos"

    if muestra_n >= 15 and concentracion_top3_pct is not None:
        if concentracion_top3_pct >= 40:
            conc_nivel, conc_texto = "alta", "Concentrado: pocos vendedores dominan las publicaciones en catálogo"
        elif concentracion_top3_pct >= 20:
            conc_nivel, conc_texto = "media", "Medianamente repartido entre varios vendedores"
        else:
            conc_nivel, conc_texto = "baja", "Fragmentado: hay lugar para entrar sin pelear contra 2-3 gigantes"
    else:
        conc_nivel, conc_texto = None, "Muestra chica: no alcanza para medir concentración de vendedores"

    if muestra_n >= 8 and iqr_relativo is not None:
        if iqr_relativo >= 0.6:
            precio_nivel, precio_texto = "amplio", "Rango de precios amplio: hay lugar para posicionarte arriba o abajo"
        elif iqr_relativo >= 0.3:
            precio_nivel, precio_texto = "medio", "Precios moderadamente dispersos"
        else:
            precio_nivel, precio_texto = "estrecho", "Precios muy parejos: se compite fino, por detalles y servicio"
    else:
        precio_nivel, precio_texto = None, None

    if comp_nivel == "alta" and conc_nivel == "alta":
        resumen = "Categoría grande y concentrada: pocos vendedores se llevan buena parte de la vitrina — entrar requiere un diferencial claro, no solo precio."
    elif comp_nivel == "alta" and conc_nivel in ("baja", "media"):
        resumen = "Categoría grande y repartida entre muchos vendedores: hay lugar, pero se gana con precio, envío y reputación."
    elif comp_nivel == "alta":
        resumen = "Categoría muy poblada: hay mucha competencia y se gana con precio, envío y reputación."
        if muestra_n:
            resumen += " La muestra de catálogo no alcanza para medir cuán concentrada está."
    elif comp_nivel == "baja":
        resumen = "Categoría chica: menos pelea, pero también menos volumen potencial — validá que haya ventas antes de invertir stock."
    else:
        resumen = "Mercado intermedio — mirá precio, envío y tu propio margen antes de decidir."

    return {
        "competencia_nivel": comp_nivel, "competencia_texto": comp_texto, "competencia_contexto": contexto,
        "concentracion_nivel": conc_nivel, "concentracion_texto": conc_texto,
        "precio_nivel": precio_nivel, "precio_texto": precio_texto,
        "resumen": resumen,
    }


def _armar_insights(pct_full, pct_envio_gratis, pct_oficial, pct_descuento, descuento_prom, mezcla):
    def n(x):  # número con coma decimal, como se lee en Argentina
        return f"{x:g}".replace(".", ",")

    insights = []
    if pct_full >= 40:
        insights.append(f"El {n(pct_full)}% de la muestra despacha con FULL — la entrega rápida es la norma acá; sin FULL competís en desventaja.")
    if pct_envio_gratis >= 60:
        insights.append(f"El {n(pct_envio_gratis)}% ofrece envío gratis — conviene absorberlo en tu precio en vez de cobrarlo aparte.")
    if pct_descuento >= 30 and descuento_prom:
        insights.append(f"El {n(pct_descuento)}% publica con descuento (promedio {n(descuento_prom)}%) — el precio de lista suele inflarse para poder mostrar la rebaja.")
    if pct_oficial >= 20:
        insights.append(f"El {n(pct_oficial)}% son tiendas oficiales de marca — competís también contra marcas con respaldo propio.")
    if mezcla and mezcla[0]["tipo"] == "Premium" and mezcla[0]["pct"] >= 50:
        insights.append(f"La mayoría ({n(mezcla[0]['pct'])}%) usa publicación Premium — es lo que ofrece cuotas sin interés al comprador.")
    return insights[:4]


def explorar_mercado(access_token, termino=None, category_id=None, site_id="MLA", liviano=False):
    """
    Análisis de mercado sobre lo que MeLi todavía deja ver por API.

    /sites/{site}/search (que usaba la versión anterior de esto) quedó
    bloqueado para apps de terceros con un 403 de PolicyAgent, sin aviso
    y para todos — no es un error de configuración de acá (otros
    desarrolladores reportan lo mismo). Y el detalle de publicaciones
    AJENAS (`/items`) también devuelve 403, así que ventas y visitas de
    la competencia ya no existen desde afuera.

    Lo que sí anda, y con lo que se arma esto: la búsqueda de catálogo
    (/products/search), las publicaciones de cada producto de catálogo
    (/products/{id}/items: precio, vendedor, envío, tipo), las
    categorías (/categories: cantidad total de publicaciones) y el
    perfil público de los vendedores (/users). La muestra son las
    publicaciones atadas a productos de catálogo — no todo el mercado —
    y se declara así en pantalla.

    Acepta termino (búsqueda libre) O category_id (navegar cualquier
    rama de MeLi) — al menos uno es obligatorio. `liviano=True` saltea
    lo decorativo (perfiles de vendedores, categorías candidatas) para
    los snapshots diarios.
    """
    termino = (termino or "").strip()
    if not termino and not category_id:
        return None
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

    candidatas, categoria = [], None
    if category_id:
        categoria = _info_categoria(headers, category_id)
        consulta = termino or (categoria or {}).get("nombre")
        if not consulta:
            return {"termino": termino, "error": "No se pudo identificar esa categoría en Mercado Libre — probá con otra."}
        # "Camperas, Tapados y Trenchs" como búsqueda literal arrastra ruido — el nombre corto rinde mejor
        consulta_catalogo = termino or consulta.split(",")[0].strip()
        objetivos = {category_id}
    else:
        consulta = consulta_catalogo = termino
        crudas = _candidatas_crudas(headers, termino, site_id)
        objetivos = {d.get("category_id") for d in crudas[:2] if d.get("category_id")}
        if crudas:
            category_id = crudas[0].get("category_id")
            if liviano:
                # Para el snapshot alcanza con el total de la categoría principal
                _, c = _get_json(f"https://api.mercadolibre.com/categories/{category_id}", headers)
                if c:
                    categoria = {"id": c.get("id"), "nombre": c.get("name"), "camino": [], "total": c.get("total_items_in_this_category"), "hermanas": None, "share_rubro_pct": None}
            else:
                candidatas = _detallar_candidatas(headers, crudas)
                categoria = _info_categoria(headers, category_id)

    revisados, estado = _buscar_catalogo(headers, consulta_catalogo, site_id, 2 if liviano else 4)
    if revisados is None:
        if estado is None:
            return {"termino": termino, "error": "No se pudo conectar con Mercado Libre — probá de nuevo en un momento."}
        return {"termino": termino, "error": f"MeLi devolvió {estado} al buscar productos — probá con otro término."}

    # /products/search matchea cada palabra en CUALQUIER rubro ("campera de jean
    # hombre" traía relojes, perfumes y libros por "hombre"): se descartan los
    # productos cuyo nombre no tiene todas las palabras de la búsqueda.
    tokens = _tokens_relevantes(consulta_catalogo)
    productos = [p for p in revisados if all(t in _normalizar(p.get("name")) for t in tokens)] if tokens else revisados
    if not productos and not categoria:
        return {"termino": termino, "error": "No encontramos productos en el catálogo de MeLi para esa búsqueda — probá con un término más general."}

    tope_productos = 20 if liviano else 40
    analizados = productos[:tope_productos]
    paralelo = 3 if liviano else 5   # MeLi devuelve 429 si se lo aprieta de más
    if analizados:
        with ThreadPoolExecutor(max_workers=paralelo) as pool:
            listas = list(pool.map(lambda p: _publicaciones_de_producto(headers, p["id"]), analizados))
    else:
        listas = []

    # Segundo filtro, más fino: la categoría real de cada publicación tiene que
    # colgar de la categoría analizada (si no, se cuela "Buzo Short Medias
    # Arquero" en una búsqueda de medias). Si el filtro deja la muestra vacía
    # se conserva todo, avisando — mejor eso que mostrar un mercado vacío.
    aviso_categorias = False
    if objetivos and any(listas):
        categorias_pub = {i.get("category_id") for lista in listas for i in lista if i.get("category_id")}
        with ThreadPoolExecutor(max_workers=paralelo) as pool:
            caminos = dict(zip(categorias_pub, pool.map(lambda c: _ids_camino(headers, c), categorias_pub)))
        listas_filtradas = [[i for i in lista if caminos.get(i.get("category_id")) and (caminos[i["category_id"]] & objetivos)] for lista in listas]
        if any(listas_filtradas):
            listas = listas_filtradas
        else:
            aviso_categorias = True

    publicaciones, referencia = [], []
    for prod, lista in zip(analizados, listas):
        if not lista:
            continue
        precios_prod = [i["price"] for i in lista if i.get("price")]
        referencia.append({
            "id": prod.get("id"), "nombre": prod.get("name"),
            "thumbnail": ((prod.get("pictures") or [{}])[0].get("url") or "").replace("http://", "https://") or None,
            "publicaciones": len(lista), "vendedores": len({i.get("seller_id") for i in lista}),
            "precio_min": min(precios_prod) if precios_prod else None,
            "precio_max": max(precios_prod) if precios_prod else None,
        })
        publicaciones.extend(lista)

    n = len(publicaciones)
    precios = sorted(i["price"] for i in publicaciones if i.get("price"))
    por_vendedor = {}
    for i in publicaciones:
        if i.get("seller_id"):
            por_vendedor[i["seller_id"]] = por_vendedor.get(i["seller_id"], 0) + 1
    ranking = sorted(por_vendedor.items(), key=lambda kv: -kv[1])

    concentracion_top3_pct = _pct(sum(c for _, c in ranking[:3]), n) if n >= 15 else None

    con_envio_gratis = sum(1 for i in publicaciones if (i.get("shipping") or {}).get("free_shipping"))
    con_full = sum(1 for i in publicaciones if (i.get("shipping") or {}).get("logistic_type") == "fulfillment")
    con_oficial = sum(1 for i in publicaciones if i.get("official_store_id"))
    descuentos = [
        (1 - i["price"] / i["original_price"]) * 100 for i in publicaciones
        if i.get("price") and i.get("original_price") and i["original_price"] > i["price"]
    ]
    tipos = {}
    for i in publicaciones:
        etiqueta = _TIPOS_PUBLICACION.get(i.get("listing_type_id"), i.get("listing_type_id") or "Otra")
        tipos[etiqueta] = tipos.get(etiqueta, 0) + 1
    mezcla_tipos = [{"tipo": t, "pct": _pct(c, n)} for t, c in sorted(tipos.items(), key=lambda kv: -kv[1])[:4]]

    marcas = {}
    for prod in productos:
        for atributo in (prod.get("attributes") or []):
            if atributo.get("id") == "BRAND" and atributo.get("value_name"):
                marcas[atributo["value_name"]] = marcas.get(atributo["value_name"], 0) + 1
    top_marcas = [{"nombre": m, "cantidad": c} for m, c in sorted(marcas.items(), key=lambda kv: -kv[1])[:8]]

    top_vendedores = []
    if not liviano and ranking:
        with ThreadPoolExecutor(max_workers=3) as pool:
            perfiles = list(pool.map(lambda kv: _perfil_vendedor(headers, kv[0]), ranking[:5]))
        for perfil, (_, cantidad) in zip(perfiles, ranking[:5]):
            perfil["publicaciones_muestra"] = cantidad
            top_vendedores.append(perfil)

    mediana = _percentil(precios, 0.5)
    iqr_relativo = None
    if len(precios) >= 8 and mediana:
        iqr_relativo = (_percentil(precios, 0.75) - _percentil(precios, 0.25)) / mediana

    pct_full, pct_envio, pct_oficial = _pct(con_full, n), _pct(con_envio_gratis, n), _pct(con_oficial, n)
    pct_descuento = _pct(len(descuentos), n)
    descuento_prom = round(sum(descuentos) / len(descuentos), 1) if descuentos else None

    avisos = []
    if aviso_categorias:
        avisos.append("Casi no hay publicaciones de catálogo dentro de esa categoría exacta, así que se incluyeron las de categorías cercanas.")
    if n == 0:
        avisos.append("Mercado Libre casi no tiene productos de catálogo para esto (pasa mucho con indumentaria, que se publica sin ficha de catálogo), así que el detalle de precios y competidores no se puede calcular. Abajo ves los datos de la categoría, que sí están completos.")
    elif n < 8:
        avisos.append(f"Solo {n} {'publicación' if n == 1 else 'publicaciones'} de catálogo para esta búsqueda: es muy poco para sacar conclusiones sobre precios o competidores.")

    total_categoria = (categoria or {}).get("total")
    return {
        "termino": termino, "category_id": category_id,
        "categoria": categoria, "categorias_candidatas": candidatas,
        "productos_catalogo": len(productos), "productos_revisados": len(revisados), "muestra_publicaciones": n,
        "total_publicaciones": total_categoria if total_categoria is not None else len(productos),
        "total_publicaciones_origen": "categoria" if total_categoria is not None else "catalogo",
        "precio_minimo": precios[0] if precios else None,
        "precio_mediano": round(mediana, 2) if mediana is not None else None,
        "precio_promedio": round(sum(precios) / len(precios), 2) if precios else None,
        "precio_maximo": precios[-1] if precios else None,
        "distribucion_precios": _histograma_precios(precios),
        "vendedores_distintos": len(por_vendedor), "concentracion_top3_pct": concentracion_top3_pct,
        "pct_envio_gratis": pct_envio, "pct_full": pct_full, "pct_tienda_oficial": pct_oficial,
        "pct_con_descuento": pct_descuento, "descuento_promedio_pct": descuento_prom,
        "mezcla_tipos": mezcla_tipos,
        "marcas": top_marcas, "marcas_distintas": len(marcas) or None,
        "top_vendedores": top_vendedores,
        "productos_referencia": sorted(referencia, key=lambda r: -r["publicaciones"])[:8],
        "insights": _armar_insights(pct_full, pct_envio, pct_oficial, pct_descuento, descuento_prom, mezcla_tipos) if n >= 8 else [],
        "avisos": avisos,
        "veredicto": _armar_veredicto_mercado(total_categoria, (categoria or {}).get("hermanas"), n, concentracion_top3_pct, iqr_relativo),
        "nota_limite": NOTA_LIMITE_DATOS,
    }


_cache_resumen_categoria = {}
TTL_RESUMEN_CATEGORIA_SEGUNDOS = 3600
_LOCK_RESUMEN_CATEGORIA = threading.Lock()


def resumen_categoria(access_token, category_id):
    """
    Versión liviana de explorar_mercado para el panel "Tu categoría" de
    la página: solo datos de categoría (2-3 llamadas, sin recorrer el
    catálogo). Se cachea una hora POR category_id — son datos públicos
    de MeLi, idénticos para cualquier cuenta, así que compartir el caché
    no cruza información entre cuentas (a diferencia de los cachés por
    cuenta que ya dieron problemas en otros módulos).
    """
    if not category_id:
        return None
    ahora = datetime.now().timestamp()
    with _LOCK_RESUMEN_CATEGORIA:
        hit = _cache_resumen_categoria.get(category_id)
        if hit and ahora - hit[0] < TTL_RESUMEN_CATEGORIA_SEGUNDOS:
            return hit[1]
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    categoria = _info_categoria(headers, category_id)
    if not categoria:
        return None
    resultado = {
        "category_id": category_id, "categoria": categoria,
        "total_publicaciones": categoria.get("total"),
        "veredicto": _armar_veredicto_mercado(categoria.get("total"), categoria.get("hermanas"), 0, None, None),
        "nota_limite": NOTA_LIMITE_DATOS,
    }
    with _LOCK_RESUMEN_CATEGORIA:
        _cache_resumen_categoria[category_id] = (ahora, resultado)
    return resultado


def estimar_margen_categoria(access_token, category_id, precio_referencia, costo_fabricacion=None):
    """
    Cruza el precio promedio de una categoría/búsqueda con la comisión
    REAL de MeLi para esa categoría (misma fuente que la Calculadora de
    Comisiones) y, si el usuario tipea un costo de fabricación
    estimado, con la ganancia neta esperada. Ni Nubimetrics ni Real
    Trends pueden hacer este cruce — no tienen tu estructura de costos.
    """
    import calculadora_costos
    if not category_id or not precio_referencia or precio_referencia <= 0:
        return None
    desglose = calculadora_costos.calcular_desglose_real(access_token, precio_referencia, category_id, "gold_special", ofrece_cuotas=False)
    if not desglose or "error" in desglose:
        return None

    resultado = {
        "precio_referencia": precio_referencia,
        "comision_estimada": desglose.get("comision_total"),
        "costo_envio_estimado": desglose.get("costo_envio"),
        "recibis_estimado": desglose.get("recibis"),
        "ganancia_neta_estimada": None, "margen_pct_estimado": None,
    }
    if costo_fabricacion is not None and costo_fabricacion > 0 and resultado["recibis_estimado"] is not None:
        ganancia_neta = resultado["recibis_estimado"] - costo_fabricacion
        resultado["ganancia_neta_estimada"] = round(ganancia_neta, 2)
        resultado["margen_pct_estimado"] = round((ganancia_neta / precio_referencia) * 100, 1)
    return resultado


_cache_categorias_raiz = {}
TTL_CATEGORIAS_RAIZ_SEGUNDOS = 24 * 3600  # las ~30 categorías raíz de MeLi casi no cambian


def obtener_categorias_raiz(access_token, site_id="MLA"):
    """
    Categorías de primer nivel de MeLi — punto de partida para navegar ramas de cualquier rubro, no solo el propio.
    Necesita token: /sites/{site}/categories sin autenticar devuelve 403 (PolicyAgent) desde que MeLi cerró sus endpoints públicos.
    """
    import time
    ahora = time.time()
    cacheado = _cache_categorias_raiz.get(site_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_CATEGORIAS_RAIZ_SEGUNDOS:
        return cacheado["data"]
    try:
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        resp = meli_http.get(f"https://api.mercadolibre.com/sites/{site_id}/categories", headers=headers, timeout=8)
        if resp.status_code != 200:
            print(f"[Tendencias] ⚠️ Categorías raíz: MeLi devolvió {resp.status_code}")
            return cacheado["data"] if cacheado else []
        resultado = [{"id": c["id"], "nombre": c["name"]} for c in resp.json()]
        _cache_categorias_raiz[site_id] = {"data": resultado, "timestamp": ahora}
        return resultado
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error trayendo categorías raíz: {e}")
        return cacheado["data"] if cacheado else []


def obtener_rama_categoria(category_id, access_token=None):
    """Subcategorías + camino (breadcrumb) de una categoría — para ir bajando ramas dentro de un rubro."""
    try:
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        resp = meli_http.get(f"https://api.mercadolibre.com/categories/{category_id}", headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "id": data.get("id"), "nombre": data.get("name"),
            "camino": [{"id": p["id"], "nombre": p["name"]} for p in (data.get("path_from_root") or [])],
            "subcategorias": [
                {"id": h["id"], "nombre": h["name"], "cantidad_publicaciones": h.get("total_items_in_this_category")}
                for h in (data.get("children_categories") or [])
            ],
        }
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error trayendo la categoría {category_id}: {e}")
        return None


# ============================================================
# Seguimiento de tendencias — construye un historial REAL en el
# tiempo (nadie más lo tiene: Real Trends solo pone una flechita de
# ">20%", nosotros guardamos snapshots de verdad). Arranca vacío por
# cuenta y se va llenando con el uso, nunca se inventa historial.
# ============================================================

def agregar_seguimiento(cursor, cuenta_id, tipo, valor, etiqueta, automatico=False):
    if tipo not in ("termino", "categoria"):
        return None
    cursor.execute("""
        INSERT INTO tendencias_seguimiento (cuenta_id, tipo, valor, etiqueta, automatico)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, tipo, valor) DO UPDATE SET etiqueta = excluded.etiqueta
        RETURNING id
    """, (cuenta_id, tipo, valor, etiqueta, automatico))
    return cursor.fetchone()[0]


def eliminar_seguimiento(cursor, cuenta_id, seguimiento_id):
    # A propósito no se puede borrar el seguimiento automático de la
    # categoría principal desde acá — se recalcula solo si el usuario
    # cambia de rubro.
    cursor.execute(
        "DELETE FROM tendencias_seguimiento WHERE cuenta_id = %s AND id = %s AND automatico = false",
        (cuenta_id, seguimiento_id)
    )
    return cursor.rowcount > 0


def asegurar_seguimiento_categoria_principal(cursor, cuenta_id, category_id, category_nombre):
    if not category_id:
        return
    # Si la categoría foco cambió (ej: pasó del rubro raíz a la categoría
    # específica), el seguimiento automático viejo sale: su historial era de
    # otra categoría y mezclarlo con el nuevo mentiría en el gráfico.
    cursor.execute(
        "DELETE FROM tendencias_seguimiento WHERE cuenta_id = %s AND automatico = true AND tipo = 'categoria' AND valor <> %s",
        (cuenta_id, category_id)
    )
    agregar_seguimiento(cursor, cuenta_id, "categoria", category_id, category_nombre or category_id, automatico=True)


def _tomar_snapshot(access_token, seguimiento, site_id="MLA"):
    """Los números del día para un seguimiento, sin tocar la base. Sin ventas: MeLi ya no las expone de terceros, así que lo que se acumula es la EVOLUCIÓN DE LA OFERTA (publicaciones, precio, vendedores)."""
    try:
        if seguimiento["tipo"] == "categoria":
            r = explorar_mercado(access_token, category_id=seguimiento["valor"], site_id=site_id, liviano=True)
        else:
            r = explorar_mercado(access_token, termino=seguimiento["valor"], site_id=site_id, liviano=True)
        if not r or r.get("error"):
            return None
        return {
            "total_publicaciones": r.get("total_publicaciones"),
            "ventas_muestra": None,
            "precio_promedio": r.get("precio_mediano"),
            "vendedores_distintos": r.get("vendedores_distintos"),
        }
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error tomando snapshot de '{seguimiento.get('etiqueta')}': {e}")
        return None


def relevar_snapshots_tendencias(access_token, cursor, cuenta_id, site_id="MLA"):
    """
    Corre una vez por día (scheduler) — toma un snapshot de HOY para
    cada término/categoría que la cuenta sigue. UPSERT por fecha, así
    una corrida repetida el mismo día no duplica ni pisa con un dato
    peor si ya se tomó temprano.
    """
    cursor.execute("SELECT id, tipo, valor, etiqueta FROM tendencias_seguimiento WHERE cuenta_id = %s", (cuenta_id,))
    seguimientos = [{"id": r[0], "tipo": r[1], "valor": r[2], "etiqueta": r[3]} for r in cursor.fetchall()]
    if not seguimientos:
        return 0

    hoy = hoy_argentina().strftime("%Y-%m-%d")
    relevados = 0

    # Consultas independientes entre sí — se resuelven en paralelo antes
    # de escribir, así una cuenta que sigue muchos términos/categorías no
    # bloquea el hilo del fallback de APScheduler (sin Redis) esperando
    # una request a la vez (mismo patrón que ads.py/despacho.py).
    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshots = list(pool.map(lambda s: _tomar_snapshot(access_token, s, site_id), seguimientos))

    for s, datos in zip(seguimientos, snapshots):
        if not datos:
            continue
        cursor.execute("""
            INSERT INTO tendencias_snapshots (cuenta_id, seguimiento_id, fecha, total_publicaciones, ventas_muestra, precio_promedio, vendedores_distintos)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (cuenta_id, seguimiento_id, fecha) DO UPDATE SET
                total_publicaciones = excluded.total_publicaciones, ventas_muestra = excluded.ventas_muestra,
                precio_promedio = excluded.precio_promedio, vendedores_distintos = excluded.vendedores_distintos
        """, (cuenta_id, s["id"], hoy, datos["total_publicaciones"], datos["ventas_muestra"], datos["precio_promedio"], datos["vendedores_distintos"]))
        relevados += 1
    return relevados


def listar_seguimientos_con_historial(cursor, cuenta_id, dias=60):
    cursor.execute("""
        SELECT id, tipo, valor, etiqueta, automatico FROM tendencias_seguimiento
        WHERE cuenta_id = %s ORDER BY automatico DESC, agregado_en DESC
    """, (cuenta_id,))
    seguimientos = cursor.fetchall()
    if not seguimientos:
        return []

    desde = (hoy_argentina() - timedelta(days=dias)).strftime("%Y-%m-%d")
    resultado = []
    for sid, tipo, valor, etiqueta, automatico in seguimientos:
        cursor.execute("""
            SELECT fecha, total_publicaciones, ventas_muestra, precio_promedio
            FROM tendencias_snapshots WHERE seguimiento_id = %s AND fecha >= %s ORDER BY fecha ASC
        """, (sid, desde))
        historial = cursor.fetchall()
        serie = [
            {"fecha": f.strftime("%Y-%m-%d") if hasattr(f, "strftime") else f, "publicaciones": p, "ventas": v,
             "precio_promedio": float(pp) if pp is not None else None}
            for f, p, v, pp in historial
        ]
        tendencia_pct = None
        if len(serie) >= 2 and serie[0]["publicaciones"]:
            tendencia_pct = round(((serie[-1]["publicaciones"] - serie[0]["publicaciones"]) / serie[0]["publicaciones"]) * 100, 1)
        resultado.append({
            "id": sid, "tipo": tipo, "valor": valor, "etiqueta": etiqueta, "automatico": automatico,
            "serie": serie, "tendencia_pct": tendencia_pct, "tiene_historial_suficiente": len(serie) >= 2,
        })
    return resultado


def detectar_movimiento_categoria_principal(cursor, cuenta_id, umbral_pct=15):
    """Para la alerta proactiva en Logros — solo dispara si el movimiento entre los últimos 2 snapshots es significativo."""
    cursor.execute("""
        SELECT id, etiqueta FROM tendencias_seguimiento
        WHERE cuenta_id = %s AND automatico = true AND tipo = 'categoria' LIMIT 1
    """, (cuenta_id,))
    fila = cursor.fetchone()
    if not fila:
        return None
    seguimiento_id, etiqueta = fila

    cursor.execute("""
        SELECT fecha, total_publicaciones FROM tendencias_snapshots
        WHERE seguimiento_id = %s AND total_publicaciones IS NOT NULL ORDER BY fecha DESC LIMIT 2
    """, (seguimiento_id,))
    filas = cursor.fetchall()
    if len(filas) < 2:
        return None

    (_, publicaciones_ultima), (_, publicaciones_anterior) = filas
    if not publicaciones_anterior:
        return None
    variacion = ((publicaciones_ultima - publicaciones_anterior) / publicaciones_anterior) * 100
    if abs(variacion) < umbral_pct:
        return None
    return {"categoria": etiqueta, "variacion_pct": round(variacion, 1), "subio": variacion > 0}


def palabras_del_catalogo(cursor):
    """Las palabras de los títulos de las publicaciones activas de la cuenta: es lo que define "su rubro" cuando MeLi no da categoría."""
    cursor.execute("SELECT titulo FROM productos_padre WHERE estado = 'active' AND titulo IS NOT NULL")
    palabras = set()
    for (titulo,) in cursor.fetchall():
        palabras.update(p for p in re.findall(r"[a-záéíóúñ]+", titulo.lower()) if len(p) > 3 and p not in PALABRAS_GENERICAS)
    return palabras


def obtener_tendencias(access_token, site_id="MLA", category_id=None, palabras_del_rubro=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/trends/{site_id}"
    if category_id:
        url += f"/{category_id}"
    try:
        resp = meli_http.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[Tendencias] ⚠️ Error consultando tendencias: {resp.status_code} - {resp.text[:200]}")
            return []
        lista = resp.json()
        for idx, t in enumerate(lista):
            kw = t.get("keyword", "").lower()
            # Con la categoría de la cuenta todo lo que devuelve MeLi es del rubro; sin ella, solo lo que comparte palabras con su catálogo
            t["relevante"] = True if category_id else any(p in kw for p in (palabras_del_rubro or ()))
            t["posicion"] = idx + 1
            t["es_top"] = idx < 20 and t["relevante"]
        return lista
    except Exception as e:
        print(f"[Tendencias] ❌ Error de conexión: {e}")
        return []


def cruzar_tendencias_con_competencia(tendencias_relevantes, cursor):
    cursor.execute("SELECT alias, titulo_actual FROM competidores_seguimiento WHERE titulo_actual IS NOT NULL")
    rivales = cursor.fetchall()
    if not rivales:
        return []
    resultado = []
    for t in tendencias_relevantes:
        if t.get("es_oportunidad"):
            kw = t.get("keyword", "").lower()
            rivales_que_la_usan = [alias or "un competidor" for alias, titulo in rivales if kw in (titulo or "").lower()]
            if rivales_que_la_usan:
                resultado.append({"keyword": t["keyword"], "rivales": rivales_que_la_usan})
    return resultado


def _enesimo_dia_semana_del_mes(anio, mes, dia_semana, n):
    d = date(anio, mes, 1)
    primeros = (dia_semana - d.weekday()) % 7
    primer = d + timedelta(days=primeros)
    return primer + timedelta(weeks=n - 1)


def _enesimo_domingo_del_mes(anio, mes, n):
    return _enesimo_dia_semana_del_mes(anio, mes, 6, n)


def obtener_calendario_estacional(anio=None):
    if anio is None:
        anio = hoy_argentina().year
    eventos = [
        {"nombre": "Vuelta al cole", "fecha": date(anio, 2, 25), "categoria_sugerida": "útiles, mochilas, tecnología y ropa escolar"},
        {"nombre": "Día de la Primavera", "fecha": date(anio, 9, 21), "categoria_sugerida": "productos de temporada, regalos y salidas al aire libre"},
        {"nombre": "Día del Padre", "fecha": _enesimo_domingo_del_mes(anio, 6, 3), "categoria_sugerida": "regalos para papá: tecnología, herramientas, indumentaria"},
        {"nombre": "Día del Amigo", "fecha": date(anio, 7, 20), "categoria_sugerida": "regalos económicos y packs para compartir"},
        {"nombre": "Día de las Infancias", "fecha": _enesimo_domingo_del_mes(anio, 8, 3), "categoria_sugerida": "juguetes, juegos y artículos infantiles"},
        {"nombre": "Día de la Madre", "fecha": _enesimo_domingo_del_mes(anio, 10, 3), "categoria_sugerida": "regalos para mamá: hogar, belleza, indumentaria"},
        {"nombre": "Black Friday", "fecha": _enesimo_dia_semana_del_mes(anio, 11, 3, 4) + timedelta(days=1), "categoria_sugerida": "todo el catálogo — el pico de ventas más grande del año"},
        {"nombre": "Navidad", "fecha": date(anio, 12, 25), "categoria_sugerida": "regalos de todo tipo y productos de temporada"},
    ]
    hoy = hoy_argentina()
    for e in eventos:
        e["fecha_str"] = e["fecha"].strftime("%d/%m/%Y")
        e["dias_faltantes"] = (e["fecha"] - hoy).days
        e["ya_paso"] = e["dias_faltantes"] < 0
    eventos = [e for e in eventos if not e["ya_paso"]]
    eventos.sort(key=lambda e: e["dias_faltantes"])
    return eventos


def cruzar_tendencias_con_catalogo(tendencias_relevantes, cursor):
    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active' ORDER BY titulo")
    activos = cursor.fetchall()
    if not activos:
        return []
    titulos_concatenados = " ".join(t.lower() for _, t in activos if t)
    oportunidades = []
    for t in tendencias_relevantes:
        termino = t.get("keyword", "").strip()
        # Marca en cada tendencia si de verdad aparece en algún título: la pantalla mostraba como "ya cubierto" todo lo que no entraba
        # en las 5 oportunidades de abajo (decía que cubrías "nike" o "lacoste" sin tenerlos en ningún título)
        t["cubierta"] = bool(termino) and termino.lower() in titulos_concatenados
        if not termino or t["cubierta"]:
            continue
        id_meli_sugerido, titulo_actual = activos[0]
        titulo_sugerido = f"{titulo_actual} {termino}"[:60]
        oportunidades.append({"termino": termino, "id_meli_sugerido": id_meli_sugerido, "titulo_actual": titulo_actual, "titulo_sugerido": titulo_sugerido})
    return oportunidades[:5]


def registrar_y_detectar_emergentes(cursor, cuenta_id, keywords_de_hoy):
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    hace_14 = (hoy_argentina() - timedelta(days=14)).strftime("%Y-%m-%d")

    cursor.execute("SELECT DISTINCT keyword FROM tendencias_historial WHERE cuenta_id = %s AND fecha >= %s AND fecha < %s", (cuenta_id, hace_14, hoy))
    vistas_antes = {r[0] for r in cursor.fetchall()}

    # Una sola sentencia para todas las palabras (antes: un INSERT por palabra, ~2 s por visita a Tendencias medido desde la PC)
    palabras = sorted({kw for kw in keywords_de_hoy if kw})
    if palabras:
        cursor.execute(
            "INSERT INTO tendencias_historial (cuenta_id, keyword, fecha) SELECT %s, k, %s FROM unnest(%s::text[]) AS k ON CONFLICT DO NOTHING",
            (cuenta_id, hoy, palabras),
        )

    hace_30 = (hoy_argentina() - timedelta(days=30)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM tendencias_historial WHERE cuenta_id = %s AND fecha < %s", (cuenta_id, hace_30))

    return {kw for kw in keywords_de_hoy if kw not in vistas_antes}


# Mercado Libre no permite texto promocional en el título (oferta, envío gratis, descuento…): la publicación puede quedar penalizada en la búsqueda.
PALABRAS_PROMOCIONALES = {"oferta", "ofertas", "promo", "promocion", "promoción", "liquidacion", "liquidación", "descuento", "barato", "outlet", "imperdible", "gratis", "cuotas"}


def calcular_seo_score_titulo(titulo, palabras_tendencia_actuales):
    """
    Puntaje 0-100 de un título para la búsqueda de MeLi, con la razón de cada punto. No hay un "MeLi trunca a los 60": en la cuenta de prueba los
    títulos van de 62 a 113 caracteres (MeLi los arma a partir del nombre de familia), así que el largo solo penaliza lo corto.
    """
    score = 100
    razones = []
    palabras_lista = [p.lower().strip(".,;:!()") for p in titulo.split()]
    palabras_titulo = {p for p in palabras_lista if p and p not in PALABRAS_RELLENO_TITULO}
    longitud = len(titulo)

    if longitud < 40:
        resta = 15
        score -= resta
        razones.append(f"-{resta}: título corto ({longitud} caracteres) — sumá tipo de producto, marca, material o uso para aparecer en más búsquedas")

    promocionales = sorted(palabras_titulo & PALABRAS_PROMOCIONALES)
    if promocionales:
        resta = 10
        score -= resta
        razones.append(f"-{resta}: tiene texto promocional ({', '.join(f'«{p}»' for p in promocionales)}) — Mercado Libre no lo permite en el título y puede penalizar la publicación")

    repetidas = sorted({p for p in palabras_titulo if len(p) > 3 and palabras_lista.count(p) > 1})
    if repetidas:
        resta = 5
        score -= resta
        razones.append(f"-{resta}: repite {', '.join(f'«{p}»' for p in repetidas)} — ese espacio rinde más con otra palabra que la gente busque")

    palabras_tendencia_en_titulo = palabras_titulo & palabras_tendencia_actuales
    if palabras_tendencia_en_titulo:
        bonus = min(len(palabras_tendencia_en_titulo) * 10, 20)
        score += bonus
        razones.append(f"+{bonus}: incluye {plural(len(palabras_tendencia_en_titulo), 'palabra')} que está{'' if len(palabras_tendencia_en_titulo) == 1 else 'n'} en tendencia esta semana")

    score = max(0, min(100, score))
    return {"score": score, "razones": razones}


def calcular_seo_scores_catalogo(cursor, tendencias_relevantes):
    palabras_tendencia = set()
    for t in tendencias_relevantes:
        palabras_tendencia.update(p.lower() for p in t.get("keyword", "").split())

    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active'")
    resultados = []
    vistos = set()
    for id_meli, titulo in cursor.fetchall():
        if not titulo:
            continue
        clave_modelo = limpiar_titulo_modelo_local(titulo)
        if clave_modelo in vistos:
            continue
        vistos.add(clave_modelo)
        analisis = calcular_seo_score_titulo(titulo, palabras_tendencia)
        resultados.append({"id_meli": id_meli, "titulo": titulo, "score": analisis["score"], "razones": analisis["razones"]})
    resultados.sort(key=lambda r: r["score"])
    return resultados


def detectar_canibalismo(cursor):
    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active'")
    filas = cursor.fetchall()
    if len(filas) < 2:
        return []

    modelos = {}
    for id_meli, titulo in filas:
        clave = limpiar_titulo_modelo_local(titulo)
        if clave not in modelos:
            modelos[clave] = {"id_referencia": id_meli, "palabras": {p for p in clave.lower().split() if len(p) > 2 and p not in PALABRAS_GENERICAS}}
    # Una palabra que está en la mayoría de los modelos de la cuenta ("termo", "campera") es el rubro, no un parecido entre dos modelos
    if len(modelos) >= 5:
        frecuencia = {}
        for m in modelos.values():
            for p in m["palabras"]:
                frecuencia[p] = frecuencia.get(p, 0) + 1
        comunes = {p for p, n in frecuencia.items() if n / len(modelos) >= 0.6}
        for m in modelos.values():
            m["palabras"] -= comunes

    claves = list(modelos.keys())
    pares_sospechosos = []
    for i in range(len(claves)):
        for j in range(i + 1, len(claves)):
            a, b = modelos[claves[i]], modelos[claves[j]]
            if not a["palabras"] or not b["palabras"]:
                continue
            interseccion = a["palabras"] & b["palabras"]
            union = a["palabras"] | b["palabras"]
            similitud = len(interseccion) / len(union) if union else 0
            if similitud >= 0.6 and len(interseccion) >= 2:
                pares_sospechosos.append({
                    "modelo_a": claves[i], "id_a": a["id_referencia"], "modelo_b": claves[j], "id_b": b["id_referencia"],
                    "palabras_compartidas": sorted(interseccion), "similitud_pct": round(similitud * 100)
                })
    pares_sospechosos.sort(key=lambda x: -x["similitud_pct"])
    return pares_sospechosos[:8]

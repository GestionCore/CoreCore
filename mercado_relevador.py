"""
Relevador global de mercado (Fase 1 del pivot multi-rubro, docs/PIVOT_SAAS.md): UNA vez por día, con el token de la APLICACIÓN (no el de ninguna cuenta), guarda la historia del
mercado de Mercado Libre en las tablas globales de la migración 0045. La historia no se puede recuperar: cada día que no se guarda se pierde para siempre.

Qué guarda, por cada categoría que sigue (todas las raíces + las lista de «Todo Mercado Libre» + cualquiera donde alguna cuenta vende o a la que alguna cuenta sigue):
  · todos los días, 2 llamadas: el tamaño de la oferta (`/categories/{id}`) y las búsquedas en alza (`/trends/MLA/{id}`: solo palabra y posición, Mercado Libre NO da volumen);
  · cada 7 días (como mucho MAX_MUESTRAS_POR_DIA por corrida), unas 23 llamadas: una muestra de los productos de catálogo de su dominio con precios (mínimo, p25, mediana, p75,
    máximo), % FULL, % envío gratis, % tienda oficial, descuentos y concentración de vendedores. Las columnas de la muestra quedan NULL los días que no se tomó;
  · cada palabra nueva se interpreta una sola vez (`domain_discovery`: «iphone 15 128 gb» → Apple / iPhone 15 / 128 GB);
  · los atributos de variación de cada categoría (`/categories/{id}/attributes`), que usa el sincronizador de las cuentas.

Datos de otras cuentas: lo único que se lee de ellas es la LISTA de categorías donde venden (`productos_padre.category_id`) y las que siguen; nunca un precio, una venta ni un título.
Reglas del lugar: las escrituras usan la conexión de administración (las tablas son de solo lectura para la app) y se hacen de a una categoría, sin mantener una conexión abierta
mientras se espera a Mercado Libre.
"""
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import config
import db
import meli_http
import mercado_categorias
from utils import hoy_argentina, percentil

URL = "https://api.mercadolibre.com"
SITIO = "MLA"                           # la lista general de tendencias del sitio se guarda con esta clave en mercado_categorias
DIAS_SIN_INTERES = 90                   # una categoría que nadie vende ni sigue desde hace tanto deja de relevarse (la historia ya guardada queda)
DIAS_ENTRE_MUESTRAS = 7
MAX_MUESTRAS_POR_DIA = 15
MAX_PRODUCTOS_POR_MUESTRA = 20
MAX_ATRIBUTOS_POR_DIA = 40
MAX_PALABRAS_POR_DIA = 300
PAUSA_ENTRE_PEDIDOS = 0.1               # segundos: es un relevamiento, no una carrera (Mercado Libre no informa su límite, ver meli_http.py)
MINIMO_PARA_CONCENTRACION = 15          # con menos ofertas que esto el % del top 3 no dice nada


# ── Pedidos a Mercado Libre ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Cliente:
    """Un token de aplicación y la cuenta de cuántos pedidos se hicieron y cuáles fallaron (para el registro de la corrida)."""

    def __init__(self, token):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.llamadas = 0
        self.errores = []

    def get(self, ruta, params=None, esperados=()):
        """(estado, json|None). Nunca levanta; un fallo se anota, salvo los estados de `esperados` (un 404 en las tendencias de una categoría solo quiere decir que no tiene)."""
        self.llamadas += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)
        estado, cuerpo = mercado_categorias._get(ruta, self.headers, params)
        if estado != 200 and estado not in esperados:
            self.errores.append(f"{ruta.split('?')[0]} → {estado}")
        return estado, cuerpo

    def categoria(self, category_id):
        self.llamadas += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)
        datos = mercado_categorias.leer_categoria(self.headers, category_id)
        if datos is None:
            self.errores.append(f"/categories/{category_id} sin respuesta")
        return datos

    def atributos(self, category_id):
        self.llamadas += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)
        atributos = mercado_categorias.leer_atributos(self.headers, category_id)
        if atributos is None:
            self.errores.append(f"/categories/{category_id}/attributes sin respuesta")
        return atributos


def obtener_token_aplicacion():
    """
    Token de la APLICACIÓN (`client_credentials`), que alcanza para todos los endpoints de mercado (verificado en docs/SONDEO_FASE0.md) y no depende de ningún cliente. Vence a las 6 horas:
    se pide uno por corrida y no se guarda en ningún lado. None si Mercado Libre no lo da.
    """
    try:
        r = meli_http.post(f"{URL}/oauth/token", data={"grant_type": "client_credentials", "client_id": config.MELI_CLIENT_ID, "client_secret": config.MELI_CLIENT_SECRET},
                           headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}, timeout=15)
        if r.status_code != 200:
            print(f"[Mercado] ⚠️ Mercado Libre no dio el token de aplicación ({r.status_code}).")
            return None
        return r.json().get("access_token")
    except Exception as e:
        print(f"[Mercado] ⚠️ No se pudo pedir el token de aplicación: {type(e).__name__}")
        return None


def normalizar_palabra(texto):
    """Minúsculas y espacios simples: es la clave del diccionario (la base exige que no tenga mayúsculas ni espacios en los bordes)."""
    return " ".join(str(texto or "").lower().split())


def palabras_en_alza(cliente, category_id):
    """Las búsquedas en alza de una categoría, en orden (la primera es el puesto 1), sin repetir; None si Mercado Libre no respondió."""
    estado, lista = cliente.get(f"/trends/{SITIO}" + ("" if category_id == SITIO else f"/{category_id}"), esperados=(404,))
    if estado != 200 or not isinstance(lista, list):
        return None
    vistas, orden = set(), []
    for t in lista:
        palabra = normalizar_palabra((t or {}).get("keyword"))
        if palabra and palabra not in vistas and len(orden) < 100:
            vistas.add(palabra)
            orden.append(palabra)
    return orden


def interpretar_palabra(cliente, texto):
    """Lo que Mercado Libre entiende de una búsqueda: {categoria_id, dominio_id, atributos}; {} si no entendió nada; None si no respondió (se reintenta otro día)."""
    estado, lista = cliente.get(f"/sites/{SITIO}/domain_discovery/search", {"q": texto, "limit": 1})
    if estado != 200 or not isinstance(lista, list):
        return None
    if not lista:
        return {}
    primero = lista[0]
    return {
        "categoria_id": primero.get("category_id"), "dominio_id": primero.get("domain_id"),
        "atributos": [{"id": a.get("id"), "name": a.get("name"), "value_id": a.get("value_id"), "value_name": a.get("value_name")} for a in primero.get("attributes") or [] if a.get("id")],
    }


# ── Muestra de catálogo: precios y logística de las ofertas ──────────────────────────────────────────────────────────────────────────────
def _porcentaje(parte, total):
    return round(parte / total * 100, 1) if total else None


def estadisticas_de_ofertas(ofertas, productos):
    """
    Resumen de las ofertas de una muestra (la forma de las columnas de `mercado_categoria_diaria`). `ofertas` son las publicaciones de `/products/{id}/items` que cuelgan de la categoría;
    `productos` cuántos productos de catálogo se revisaron. La concentración de vendedores solo se calcula con MINIMO_PARA_CONCENTRACION ofertas o más.
    """
    precios = sorted(float(o["price"]) for o in ofertas if o.get("price"))
    n = len(ofertas)
    por_vendedor = Counter(o.get("seller_id") for o in ofertas if o.get("seller_id"))
    con_descuento = [(1 - o["price"] / o["original_price"]) * 100 for o in ofertas if o.get("price") and o.get("original_price") and o["original_price"] > o["price"]]
    concentracion = hhi = None
    if n >= MINIMO_PARA_CONCENTRACION and por_vendedor:
        concentracion = _porcentaje(sum(c for _, c in por_vendedor.most_common(3)), n)
        hhi = round(sum((c / n * 100) ** 2 for c in por_vendedor.values()))
    return {
        "muestra_productos": productos, "muestra_ofertas": n, "muestra_vendedores": len(por_vendedor),
        "precio_min": round(precios[0], 2) if precios else None, "precio_p25": round(percentil(precios, 0.25), 2) if precios else None,
        "precio_p50": round(percentil(precios, 0.5), 2) if precios else None, "precio_p75": round(percentil(precios, 0.75), 2) if precios else None,
        "precio_max": round(precios[-1], 2) if precios else None,
        "pct_full": _porcentaje(sum(1 for o in ofertas if (o.get("shipping") or {}).get("logistic_type") == "fulfillment"), n),
        "pct_envio_gratis": _porcentaje(sum(1 for o in ofertas if (o.get("shipping") or {}).get("free_shipping")), n),
        "pct_tienda_oficial": _porcentaje(sum(1 for o in ofertas if o.get("official_store_id")), n),
        "pct_con_descuento": _porcentaje(len(con_descuento), n),
        "descuento_promedio": round(sum(con_descuento) / len(con_descuento), 1) if con_descuento else None,
        "concentracion_top3": concentracion, "hhi": hhi,
    }


def tomar_muestra(cliente, categoria):
    """
    Muestra de precios de una categoría HOJA: los productos de catálogo de su dominio (`/products/search` con el nombre del dominio como texto —la búsqueda exige un texto— y `domain_id`
    como filtro: verificado que solo devuelve productos de ese dominio) y las ofertas de los primeros MAX_PRODUCTOS_POR_MUESTRA que cuelgan EXACTAMENTE de esa categoría.
    None si no se puede (sin dominio, no es hoja, o Mercado Libre no respondió); un dict con `muestra_ofertas` en 0 si respondió pero no había ofertas.
    """
    dominio = categoria.get("dominio_id")
    if not dominio or not categoria.get("es_hoja"):
        return None
    estado, ficha = cliente.get(f"/catalog_domains/{dominio}")
    nombre = (ficha or {}).get("name") if estado == 200 else None
    if not nombre:
        return None
    estado, busqueda = cliente.get("/products/search", {"site_id": SITIO, "status": "active", "q": nombre, "domain_id": dominio, "limit": MAX_PRODUCTOS_POR_MUESTRA})
    if estado != 200:
        return None
    productos = [p["id"] for p in (busqueda or {}).get("results") or [] if p.get("id") and p.get("domain_id") == dominio][:MAX_PRODUCTOS_POR_MUESTRA]

    def _ofertas(producto_id):
        cliente.llamadas += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)
        e, j = mercado_categorias._get(f"/products/{producto_id}/items", cliente.headers, {"limit": 50})
        return (j or {}).get("results") or [] if e == 200 else []

    with ThreadPoolExecutor(max_workers=3) as pool:
        listas = list(pool.map(_ofertas, productos))
    ofertas = [o for lista in listas for o in lista if o.get("category_id") == categoria["category_id"]]
    return estadisticas_de_ofertas(ofertas, len(productos))


# ── Estado de las palabras en alza ───────────────────────────────────────────────────────────────────────────────────────────────────────
def calcular_estado(previo, orden, fecha, hace_7_dias):
    """
    El estado de cada palabra después de la lista de `fecha`. `previo` es {keyword_id: {primera_vez, ultima_vez, racha_dias, dias_en_lista, mejor_posicion, posicion_actual}};
    `orden` los ids de hoy (el primero es el puesto 1); `hace_7_dias` {keyword_id: puesto} de la lista de hace una semana. Devuelve las filas a guardar:
    (keyword_id, primera_vez, ultima_vez, racha_dias, dias_en_lista, mejor_posicion, posicion_actual, posicion_hace_7d).
    Repetir la corrida el mismo día no suma días ni rachas; una palabra que sale de la lista conserva su historia con `posicion_actual` en None.
    """
    hoy = {kid: pos for pos, kid in enumerate(orden, 1)}
    filas = []
    for kid, pos in hoy.items():
        p = previo.get(kid)
        if p is None:
            filas.append((kid, fecha, fecha, 1, 1, pos, pos, hace_7_dias.get(kid)))
            continue
        if p["ultima_vez"] == fecha:
            racha, dias = p["racha_dias"], p["dias_en_lista"]
        elif p["ultima_vez"] == fecha - timedelta(days=1):
            racha, dias = p["racha_dias"] + 1, p["dias_en_lista"] + 1
        else:
            racha, dias = 1, p["dias_en_lista"] + 1
        filas.append((kid, p["primera_vez"], fecha, racha, dias, min(p["mejor_posicion"], pos), pos, hace_7_dias.get(kid)))
    for kid, p in previo.items():
        if kid not in hoy and p["posicion_actual"] is not None:
            filas.append((kid, p["primera_vez"], p["ultima_vez"], p["racha_dias"], p["dias_en_lista"], p["mejor_posicion"], None, hace_7_dias.get(kid)))
    return filas


# ── Escritura de lo relevado (con la conexión de administración, de a una categoría) ─────────────────────────────────────────────────────
def guardar_tendencias(cursor, category_id, fecha, palabras):
    """Guarda la lista del día (arreglo de ids del diccionario) y actualiza el estado de cada palabra. Devuelve cuántas palabras eran nuevas."""
    if palabras:
        cursor.execute("SELECT count(*) FROM mercado_keywords WHERE texto = ANY(%s)", (palabras,))
        conocidas = cursor.fetchone()[0]
        cursor.execute("INSERT INTO mercado_keywords (texto, primera_vez) SELECT t, %s FROM unnest(%s::text[]) AS t ON CONFLICT (texto) DO NOTHING", (fecha, palabras))
        cursor.execute("SELECT texto, id FROM mercado_keywords WHERE texto = ANY(%s)", (palabras,))
        ids = dict(cursor.fetchall())
    else:
        conocidas, ids = 0, {}
    orden = [ids[p] for p in palabras]
    cursor.execute(
        """INSERT INTO mercado_tendencias_diaria (category_id, fecha, keywords) VALUES (%s, %s, %s)
           ON CONFLICT (category_id, fecha) DO UPDATE SET keywords = EXCLUDED.keywords, tomada_en = now()""",
        (category_id, fecha, orden),
    )

    cursor.execute(
        """SELECT keyword_id, primera_vez, ultima_vez, racha_dias, dias_en_lista, mejor_posicion, posicion_actual
           FROM mercado_keyword_estado WHERE category_id = %s""", (category_id,))
    previo = {f[0]: {"primera_vez": f[1], "ultima_vez": f[2], "racha_dias": f[3], "dias_en_lista": f[4], "mejor_posicion": f[5], "posicion_actual": f[6]} for f in cursor.fetchall()}
    cursor.execute("SELECT keywords FROM mercado_tendencias_diaria WHERE category_id = %s AND fecha = %s", (category_id, fecha - timedelta(days=7)))
    fila = cursor.fetchone()
    hace_7_dias = {kid: pos for pos, kid in enumerate(fila[0], 1)} if fila else {}
    filas = calcular_estado(previo, orden, fecha, hace_7_dias)
    if filas:
        cursor.executemany(
            """INSERT INTO mercado_keyword_estado (category_id, keyword_id, primera_vez, ultima_vez, racha_dias, dias_en_lista, mejor_posicion, posicion_actual, posicion_hace_7d)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (category_id, keyword_id) DO UPDATE SET
                   ultima_vez = EXCLUDED.ultima_vez, racha_dias = EXCLUDED.racha_dias, dias_en_lista = EXCLUDED.dias_en_lista, mejor_posicion = EXCLUDED.mejor_posicion,
                   posicion_actual = EXCLUDED.posicion_actual, posicion_hace_7d = EXCLUDED.posicion_hace_7d""",
            [(category_id, *f) for f in filas],
        )
    return len(palabras) - conocidas


def guardar_publicaciones(cursor, category_id, fecha, publicaciones):
    cursor.execute(
        """INSERT INTO mercado_categoria_diaria (category_id, fecha, publicaciones) VALUES (%s, %s, %s)
           ON CONFLICT (category_id, fecha) DO UPDATE SET publicaciones = EXCLUDED.publicaciones, tomada_en = now()""",
        (category_id, fecha, publicaciones),
    )


def guardar_muestra(cursor, category_id, fecha, m):
    columnas = ("muestra_productos", "muestra_ofertas", "muestra_vendedores", "precio_min", "precio_p25", "precio_p50", "precio_p75", "precio_max", "pct_full", "pct_envio_gratis",
                "pct_tienda_oficial", "pct_con_descuento", "descuento_promedio", "concentracion_top3", "hhi")
    cursor.execute(
        f"""INSERT INTO mercado_categoria_diaria (category_id, fecha, {', '.join(columnas)}) VALUES (%s, %s, {', '.join(['%s'] * len(columnas))})
            ON CONFLICT (category_id, fecha) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in columnas)}, tomada_en = now()""",
        (category_id, fecha, *[m[c] for c in columnas]),
    )


# ── Qué categorías se siguen ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def actualizar_interes(cursor, fecha):
    """
    Marca para el relevamiento diario las categorías que alguna cuenta vende o sigue, y suelta las que nadie mira desde hace DIAS_SIN_INTERES (la historia queda). Las raíces y
    la lista general nunca se sueltan. De las cuentas solo se lee qué categorías son, nunca sus datos. Devuelve los ids de todas las que quedan seguidas.
    """
    cursor.execute("SELECT DISTINCT category_id FROM productos_padre WHERE estado = 'active' AND category_id IS NOT NULL")
    ids = {f[0] for f in cursor.fetchall()}
    cursor.execute("SELECT DISTINCT valor FROM tendencias_seguimiento WHERE tipo = 'categoria'")
    ids |= {f[0] for f in cursor.fetchall()}
    if ids:
        cursor.execute(
            "INSERT INTO mercado_categorias (category_id, nombre) SELECT c, c FROM unnest(%s::text[]) AS c ON CONFLICT (category_id) DO NOTHING", (sorted(ids),))
        cursor.execute("UPDATE mercado_categorias SET seguida = true, ultimo_interes = %s WHERE category_id = ANY(%s)", (fecha, sorted(ids)))
    cursor.execute("UPDATE mercado_categorias SET seguida = true, ultimo_interes = %s WHERE category_id = %s OR cardinality(camino) = 1", (fecha, SITIO))
    cursor.execute("UPDATE mercado_categorias SET seguida = false WHERE seguida AND ultimo_interes < %s", (fecha - timedelta(days=DIAS_SIN_INTERES),))
    cursor.execute("SELECT category_id FROM mercado_categorias WHERE seguida ORDER BY category_id")
    return [f[0] for f in cursor.fetchall()]


def cargar_raices(cliente, cursor, fecha):
    """Las categorías de primer nivel (`/sites/MLA/categories`), solo si todavía no están todas. Devuelve cuántas dio de alta."""
    cursor.execute("SELECT count(*) FROM mercado_categorias WHERE cardinality(camino) = 1 AND category_id <> %s", (SITIO,))
    if cursor.fetchone()[0] >= 10:
        return 0
    estado, lista = cliente.get(f"/sites/{SITIO}/categories")
    if estado != 200 or not isinstance(lista, list):
        return 0
    for c in lista:
        if c.get("id"):
            cursor.execute(
                """INSERT INTO mercado_categorias (category_id, nombre, camino, camino_nombres, es_hoja, seguida, ultimo_interes)
                   VALUES (%s, %s, %s, %s, false, true, %s) ON CONFLICT (category_id) DO NOTHING""",
                (c["id"], c.get("name") or c["id"], [c["id"]], [c.get("name") or c["id"]], fecha),
            )
    return len(lista)


# ── La corrida diaria ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def relevar_si_falta(hoy=None):
    """
    `relevar()` solo si hoy todavía no hay un relevamiento terminado ni uno en marcha (empezado hace menos de 2 horas). Devuelve su resumen, o None si no hizo falta. El scheduler
    lo llama cada hora: así un día sin proceso (reinicio, deploy, caída) se recupera solo en cuanto vuelve.
    """
    fecha = hoy or hoy_argentina()
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """SELECT 1 FROM mercado_relevamientos WHERE tipo = 'diario' AND fecha = %s
                 AND (fin IS NOT NULL OR inicio > now() - interval '2 hours') LIMIT 1""", (fecha,))
        if cursor.fetchone():
            return None
    return relevar(fecha)


def relevar(hoy=None):
    """
    Lo que corre el scheduler una vez por día (y a mano la primera vez). Devuelve un resumen. Repetirlo el mismo día es seguro: todo se guarda por (categoría, fecha).
    """
    fecha = hoy or hoy_argentina()
    inicio = time.time()
    token = obtener_token_aplicacion()
    if not token:
        return {"error": "sin token de aplicación"}
    cliente = Cliente(token)
    resumen = {"fecha": str(fecha), "categorias": 0, "con_tendencias": 0, "palabras_nuevas": 0, "muestras": 0, "atributos": 0, "interpretadas": 0}

    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("INSERT INTO mercado_relevamientos (tipo, fecha) VALUES ('diario', %s) RETURNING id", (fecha,))
        relevamiento_id = cursor.fetchone()[0]
        cargar_raices(cliente, cursor, fecha)
        seguidas = actualizar_interes(cursor, fecha)

    for category_id in seguidas:                                    # lo diario: tamaño de la oferta y búsquedas en alza
        datos = None if category_id == SITIO else cliente.categoria(category_id)
        palabras = palabras_en_alza(cliente, category_id)
        if datos is None and palabras is None:
            continue
        try:
            with db.conexion_admin() as conexion:
                cursor = conexion.cursor()
                if datos:
                    mercado_categorias.guardar_categoria(cursor, datos)
                    if datos.get("publicaciones") is not None:
                        guardar_publicaciones(cursor, category_id, fecha, datos["publicaciones"])
                if palabras is not None:
                    resumen["palabras_nuevas"] += guardar_tendencias(cursor, category_id, fecha, palabras)
                    resumen["con_tendencias"] += 1
            resumen["categorias"] += 1
        except Exception as e:
            cliente.errores.append(f"guardar {category_id}: {type(e).__name__}")
            print(f"[Mercado] ❌ No se pudo guardar {category_id}: {e}")

    _muestras_pendientes(cliente, fecha, resumen)
    _atributos_pendientes(cliente, resumen)
    _palabras_pendientes(cliente, resumen)

    with db.conexion_admin() as conexion:
        conexion.cursor().execute(
            """UPDATE mercado_relevamientos SET fin = now(), categorias = %s, llamadas = %s, errores = %s, detalle = %s::jsonb WHERE id = %s""",
            (resumen["categorias"], cliente.llamadas, len(cliente.errores), _json({**resumen, "segundos": round(time.time() - inicio), "primeros_errores": cliente.errores[:15]}), relevamiento_id),
        )
    resumen.update(llamadas=cliente.llamadas, errores=len(cliente.errores), segundos=round(time.time() - inicio))
    return resumen


def _json(valor):
    import json
    return json.dumps(valor, ensure_ascii=False, default=str)


def _muestras_pendientes(cliente, fecha, resumen):
    """Las hojas con dominio cuya última muestra tiene más de DIAS_ENTRE_MUESTRAS días (o nunca tuvo), las más viejas primero."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """SELECT c.category_id FROM mercado_categorias c
               LEFT JOIN LATERAL (SELECT max(fecha) AS ultima FROM mercado_categoria_diaria d WHERE d.category_id = c.category_id AND d.muestra_ofertas IS NOT NULL) m ON true
               WHERE c.seguida AND c.es_hoja AND c.dominio_id IS NOT NULL AND (m.ultima IS NULL OR m.ultima <= %s)
               ORDER BY m.ultima NULLS FIRST, c.category_id LIMIT %s""",
            (fecha - timedelta(days=DIAS_ENTRE_MUESTRAS), MAX_MUESTRAS_POR_DIA),
        )
        pendientes = [f[0] for f in cursor.fetchall()]
    for category_id in pendientes:
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT category_id, dominio_id, es_hoja FROM mercado_categorias WHERE category_id = %s", (category_id,))
            f = cursor.fetchone()
        muestra = tomar_muestra(cliente, {"category_id": f[0], "dominio_id": f[1], "es_hoja": f[2]}) if f else None
        if muestra is None:
            continue
        try:
            with db.conexion_admin() as conexion:
                guardar_muestra(conexion.cursor(), category_id, fecha, muestra)
            resumen["muestras"] += 1
        except Exception as e:
            cliente.errores.append(f"muestra {category_id}: {type(e).__name__}")


def _atributos_pendientes(cliente, resumen):
    """Los atributos de variación de las categorías seguidas que nunca se pidieron o pasaron la vigencia (los usa el sincronizador de cada cuenta)."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """SELECT category_id FROM mercado_categorias
               WHERE seguida AND cardinality(camino) > 1 AND (atributos_en IS NULL OR atributos_en < now() - make_interval(days => %s))
               ORDER BY atributos_en NULLS FIRST, category_id LIMIT %s""",
            (mercado_categorias.DIAS_VIGENCIA_ATRIBUTOS, MAX_ATRIBUTOS_POR_DIA),
        )
        pendientes = [f[0] for f in cursor.fetchall()]
    for category_id in pendientes:
        atributos = cliente.atributos(category_id)
        if atributos is None:
            continue
        with db.conexion_admin() as conexion:
            mercado_categorias.guardar_atributos(conexion.cursor(), category_id, *atributos)
        resumen["atributos"] += 1


def _palabras_pendientes(cliente, resumen):
    """Interpreta (una sola vez por palabra) las que todavía no se entendieron, hasta MAX_PALABRAS_POR_DIA por corrida."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, texto FROM mercado_keywords WHERE interpretada_en IS NULL ORDER BY id LIMIT %s", (MAX_PALABRAS_POR_DIA,))
        pendientes = cursor.fetchall()
    for palabra_id, texto in pendientes:
        interpretacion = interpretar_palabra(cliente, texto)
        if interpretacion is None:
            continue
        with db.conexion_admin() as conexion:
            conexion.cursor().execute(
                "UPDATE mercado_keywords SET categoria_id = %s, dominio_id = %s, atributos = %s::jsonb, interpretada_en = now() WHERE id = %s",
                (interpretacion.get("categoria_id"), interpretacion.get("dominio_id"), _json(interpretacion.get("atributos") or []), palabra_id),
            )
        resumen["interpretadas"] += 1

"""
Espía de Competencia — seguimiento de PRODUCTOS DE CATÁLOGO.

Mercado Libre dejó de exponer por API el precio, el stock y las ventas de
publicaciones de otros vendedores: GET /items/{id} de una publicación ajena
devuelve 403 aun con el token del vendedor. Lo que sí se puede ver es la ficha
de catálogo de un producto (/products/{id}) y todas las ofertas activas que
compiten ahí (/products/{id}/items: precio, vendedor, envío gratis, FULL).

Por eso lo que se sigue ahora es el producto de catálogo, no la publicación de
un rival puntual: cada día se guarda cuántas ofertas y vendedores hay y cómo se
reparte el precio. La tabla conserva el nombre `competidores_*` (y la columna
`id_meli_rival`, que ahora guarda el ID del producto de catálogo) para no tocar
el esquema existente.
"""
import re
import meli_http
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from utils import ARGENTINA, hoy_argentina

# Fichas de catálogo: MLA + 6 a 8 dígitos (MLA63419087). Las publicaciones
# puntuales tienen 9-10 dígitos (MLA2841280276) y esas ya no se pueden seguir.
_RE_PRODUCTO_URL = re.compile(r"/p/(MLA\d{5,9})", re.IGNORECASE)
_RE_ID_SUELTO = re.compile(r"(?<![A-Za-z0-9])(MLA)-?(\d{5,12})(?!\d)", re.IGNORECASE)

MENSAJE_PUBLICACION_PUNTUAL = (
    "Ese ID es de una publicación puntual, y Mercado Libre ya no permite consultar precio, stock ni ventas "
    "de publicaciones de otros vendedores. Lo que sí se puede seguir es un producto de catálogo: pegá el link "
    "de su ficha (el que tiene /p/MLA… en la dirección) o el ID del producto."
)


def extraer_id_producto(texto):
    """
    Devuelve (id_producto, error). Acepta el link de la ficha de catálogo
    (.../p/MLA63419087), el ID pelado (MLA63419087) o un link con el ID. Si es
    el ID de una publicación puntual (9+ dígitos) devuelve un error explicando
    qué sí se puede seguir.
    """
    texto = (texto or "").strip()
    if not texto:
        return None, "Pegá el link o el ID de un producto de catálogo."
    m = _RE_PRODUCTO_URL.search(texto)
    if m:
        return m.group(1).upper(), None
    m = _RE_ID_SUELTO.search(texto)
    if not m:
        return None, "No encontramos un ID de Mercado Libre en ese texto — pegá el link de la ficha de catálogo (/p/MLA…) o el ID."
    digitos = m.group(2)
    if len(digitos) >= 9:
        return None, MENSAJE_PUBLICACION_PUNTUAL
    return f"MLA{digitos}", None


def _get_json(url, headers, params=None, timeout=10):
    try:
        resp = meli_http.get(url, headers=headers, params=params, timeout=timeout)
    except Exception as e:
        print(f"[Espía Competencia] ⚠️ Error de conexión con {url}: {e}")
        return None, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def _miniatura(producto):
    fotos = producto.get("pictures") or []
    url = (fotos[0].get("url") if fotos else None) or ""
    return url.replace("http://", "https://") or None


def agregar_competidor(cursor, access_token, cuenta_id, texto, alias=""):
    """
    Valida el producto contra MeLi antes de guardarlo (así un ID mal tipeado
    falla ahora, no en silencio durante semanas). Devuelve (ok, mensaje).
    """
    id_producto, error = extraer_id_producto(texto)
    if error:
        return False, error

    headers = {"Authorization": f"Bearer {access_token}"}
    estado, producto = _get_json(f"https://api.mercadolibre.com/products/{id_producto}", headers)
    if estado == 404:
        return False, f"No existe un producto de catálogo con el ID {id_producto} — revisá el link."
    if not producto:
        return False, "No pudimos consultar ese producto en Mercado Libre ahora mismo — probá de nuevo en un momento."

    ahora = datetime.now(ARGENTINA).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO competidores_seguimiento (cuenta_id, id_meli_rival, alias, titulo_actual, thumbnail, agregado_en)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, id_meli_rival) DO UPDATE SET alias = excluded.alias, titulo_actual = excluded.titulo_actual, thumbnail = excluded.thumbnail
    """, (cuenta_id, id_producto, alias, producto.get("name"), _miniatura(producto), ahora))

    # Primer dato en el momento, así la pantalla no queda vacía hasta mañana
    _guardar_relevamiento(cursor, cuenta_id, id_producto, _relevar_producto(headers, id_producto))
    return True, f"Ahora seguís «{producto.get('name') or id_producto}»."


def eliminar_competidor(cursor, cuenta_id, id_producto):
    cursor.execute("DELETE FROM competidores_seguimiento WHERE cuenta_id = %s AND id_meli_rival = %s", (cuenta_id, id_producto.upper()))
    cursor.execute("DELETE FROM competidores_historial WHERE cuenta_id = %s AND id_meli_rival = %s", (cuenta_id, id_producto.upper()))


def _percentil(ordenados, p):
    if not ordenados:
        return None
    if len(ordenados) == 1:
        return ordenados[0]
    k = (len(ordenados) - 1) * p
    piso = int(k)
    techo = min(piso + 1, len(ordenados) - 1)
    return ordenados[piso] + (ordenados[techo] - ordenados[piso]) * (k - piso)


def _relevar_producto(headers, id_producto):
    """Los números de hoy de un producto de catálogo, o None si MeLi no respondió."""
    estado, data = _get_json(f"https://api.mercadolibre.com/products/{id_producto}/items", headers, {"limit": 50})
    if estado == 404:
        # "No winners found": el producto existe pero hoy no tiene ofertas activas
        return {"ofertas": 0, "vendedores": 0, "precio_min": None, "precio_mediano": None, "precio_max": None, "pct_full": None}
    if data is None:
        return None
    ofertas = data.get("results") or []
    precios = sorted(o["price"] for o in ofertas if o.get("price"))
    con_full = sum(1 for o in ofertas if (o.get("shipping") or {}).get("logistic_type") == "fulfillment")
    total = (data.get("paging") or {}).get("total")   # si hay más de 50 ofertas, los precios salen de las primeras 50
    return {
        "ofertas": total if isinstance(total, int) else len(ofertas),
        "vendedores": len({o.get("seller_id") for o in ofertas if o.get("seller_id")}),
        "precio_min": precios[0] if precios else None,
        "precio_mediano": round(_percentil(precios, 0.5), 2) if precios else None,
        "precio_max": precios[-1] if precios else None,
        "pct_full": round(con_full / len(ofertas) * 100, 1) if ofertas else None,
    }


def _guardar_relevamiento(cursor, cuenta_id, id_producto, datos):
    if not datos:
        return False
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    cursor.execute("""
        INSERT INTO competidores_historial (cuenta_id, id_meli_rival, fecha, precio, precio_mediano, precio_max, ofertas, vendedores, pct_full)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, id_meli_rival, fecha) DO UPDATE SET
            precio = excluded.precio, precio_mediano = excluded.precio_mediano, precio_max = excluded.precio_max,
            ofertas = excluded.ofertas, vendedores = excluded.vendedores, pct_full = excluded.pct_full
    """, (cuenta_id, id_producto, hoy, datos["precio_min"], datos["precio_mediano"], datos["precio_max"],
          datos["ofertas"], datos["vendedores"], datos["pct_full"]))
    return True


def relevar_competidores(cursor, cuenta_id, access_token):
    cursor.execute("SELECT id_meli_rival FROM competidores_seguimiento WHERE cuenta_id = %s", (cuenta_id,))
    productos = [r[0] for r in cursor.fetchall()]
    if not productos:
        return 0

    headers = {"Authorization": f"Bearer {access_token}"}
    # Consultas independientes entre sí — en paralelo (pocas a la vez: MeLi
    # devuelve 429 si se lo aprieta), y recién después se escribe en serie.
    with ThreadPoolExecutor(max_workers=3) as pool:
        resultados = list(pool.map(lambda pid: _relevar_producto(headers, pid), productos))

    relevados = 0
    for id_producto, datos in zip(productos, resultados):
        try:
            if _guardar_relevamiento(cursor, cuenta_id, id_producto, datos):
                relevados += 1
        except Exception as e:
            print(f"[Espía Competencia] ⚠️ Error guardando {id_producto}: {e}")
    return relevados


def ids_publicaciones_propias(cursor, limite=40):
    cursor.execute("SELECT id_meli FROM productos_padre WHERE estado = 'active' ORDER BY id_meli LIMIT %s", (limite,))
    return [f[0] for f in cursor.fetchall()]


def sugerir_productos_propios(access_token, ids_propios, ya_seguidos):
    """
    Publicaciones propias que están dentro de un producto de catálogo — el
    punto de partida natural para ver contra quién se compite. Usa el detalle
    de las publicaciones PROPIAS (eso sí lo permite MeLi). Devuelve lista de
    {id_producto, titulo, publicaciones_propias}, sin los que ya se siguen.
    Recibe los IDs ya leídos de la base para no hacer la llamada a MeLi con
    una conexión del pool ocupada.
    """
    if not ids_propios:
        return []
    headers = {"Authorization": f"Bearer {access_token}"}
    estado, data = _get_json("https://api.mercadolibre.com/items", headers, {"ids": ",".join(ids_propios), "attributes": "id,title,catalog_product_id"})
    if estado != 200 or not isinstance(data, list):
        return []

    por_producto = {}
    for fila in data:
        cuerpo = fila.get("body") or {}
        pid = cuerpo.get("catalog_product_id") if fila.get("code") == 200 else None
        if not pid or pid in ya_seguidos:
            continue
        item = por_producto.setdefault(pid, {"id_producto": pid, "titulo": cuerpo.get("title"), "publicaciones_propias": 0})
        item["publicaciones_propias"] += 1
    return sorted(por_producto.values(), key=lambda s: -s["publicaciones_propias"])[:6]


def obtener_panorama_competencia(cursor, cuenta_id):
    cursor.execute(
        "SELECT id_meli_rival, alias, titulo_actual, thumbnail FROM competidores_seguimiento WHERE cuenta_id = %s ORDER BY agregado_en DESC",
        (cuenta_id,)
    )
    productos = cursor.fetchall()

    panorama = []
    for id_producto, alias, titulo_actual, thumbnail in productos:
        cursor.execute("""
            SELECT fecha, precio, precio_mediano, precio_max, ofertas, vendedores, pct_full
            FROM competidores_historial WHERE cuenta_id = %s AND id_meli_rival = %s AND ofertas IS NOT NULL
            ORDER BY fecha DESC LIMIT 14
        """, (cuenta_id, id_producto))
        historial = cursor.fetchall()

        # Cambio del precio más bajo entre el primer y el último dato disponible
        tendencia_precio = None
        if len(historial) >= 2:
            precio_hoy, precio_antes = historial[0][1], historial[-1][1]
            if precio_hoy is not None and precio_antes and precio_hoy != precio_antes:
                tendencia_precio = "bajó" if precio_hoy < precio_antes else "subió"

        # Sparkline del precio mínimo — el historial viene DESC (hoy primero)
        # pero se lee de izquierda a derecha en el tiempo, así que se invierte.
        precios = [float(h[1]) for h in reversed(historial) if h[1] is not None]
        sparkline_puntos = None
        if len(precios) >= 2:
            minimo, maximo = min(precios), max(precios)
            rango = (maximo - minimo) or 1
            ancho_svg, alto_svg = 70, 24
            paso_x = ancho_svg / (len(precios) - 1)
            puntos = []
            for idx, valor in enumerate(precios):
                x = round(idx * paso_x, 1)
                y = round(alto_svg - ((valor - minimo) / rango) * (alto_svg - 4) - 2, 1)
                puntos.append(f"{x},{y}")
            sparkline_puntos = " ".join(puntos)

        panorama.append({
            "id_producto": id_producto, "alias": alias or titulo_actual or id_producto, "titulo_actual": titulo_actual,
            "thumbnail": thumbnail,
            "historial": [{
                "fecha": h[0].strftime("%Y-%m-%d") if hasattr(h[0], "strftime") else h[0],
                "precio_min": float(h[1]) if h[1] is not None else None,
                "precio_mediano": float(h[2]) if h[2] is not None else None,
                "precio_max": float(h[3]) if h[3] is not None else None,
                "ofertas": h[4], "vendedores": h[5], "pct_full": float(h[6]) if h[6] is not None else None,
            } for h in historial],
            "tendencia_precio": tendencia_precio,
            "sparkline_puntos": sparkline_puntos,
        })
    return panorama

"""
Embudo de Conversión — portado de Santi Mens. Bug de fuga entre
cuentas encontrado (misma familia que en ads.py, facturacion.py,
logistica.py y tendencias.py): `_cache_embudo` y `_cache_zombies` eran
sendos slots globales únicos — la primera cuenta que consultara dejaba
SU embudo/zombies cacheado para cualquier otra cuenta que consultara
después. Ahora `_cache_embudo` se indexa por cuenta_id y las visitas de
las zombies viven en `cache_db` (por cuenta, compartidas entre procesos).
"""
import meli_http
import time
import cache_db
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import hoy_argentina

_cache_embudo = {}
TTL_SEGUNDOS = 900
CLAVE_VISITAS_ZOMBIES = "visitas_zombies"
TTL_VISITA_SEGUNDOS = 6 * 3600          # las visitas de 60 días casi no se mueven en horas; antes: 79 llamadas a Mercado Libre (2,2 s) cada 15 min por proceso


def _obtener_visitas_un_item(headers, id_item, date_from, date_to):
    """(id, visitas). None = Mercado Libre no lo supo informar: NO es «0 visitas» (una publicación con visitas se marcaría como zombie por un error pasajero)."""
    try:
        resp = meli_http.get(
            f"https://api.mercadolibre.com/items/{id_item}/visits",
            headers=headers, params={"date_from": date_from, "date_to": date_to}, timeout=8
        )
        if resp.status_code != 200:
            return id_item, None
        data = resp.json()
        if isinstance(data, dict):
            visitas = data.get("total_visits") or data.get("visits") or data.get("quantity") or 0
            return id_item, visitas
        if isinstance(data, list) and data:
            visitas = data[0].get("total_visits") or data[0].get("visits") or data[0].get("quantity") or 0
            return id_item, visitas
    except Exception as e:
        print(f"[Embudo] ⚠️ No se pudieron traer las visitas de {id_item}: {e}")
    return id_item, None


def obtener_visitas_items(headers, ids_lista, date_from, date_to):
    if not ids_lista:
        return {}
    resultado = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futuros = {pool.submit(_obtener_visitas_un_item, headers, id_item, date_from, date_to): id_item for id_item in ids_lista}
        for futuro in as_completed(futuros):
            try:
                id_item, visitas = futuro.result()
                resultado[id_item] = visitas
            except Exception as e:
                print(f"[Embudo] ⚠️ Error procesando visitas: {e}")
    return resultado


def visitas_con_cache(headers, cuenta_id, cursor, ids_lista, date_from, date_to, dias, ahora=None):
    """
    {id: visitas o None} de cada publicación. Las visitas de la ventana de `dias` se guardan en cache_db (compartidas entre los procesos) con la hora de CADA dato:
    pasadas 6 h esa publicación se vuelve a pedir, las demás no, y un dato nuevo no rejuvenece a los viejos. Solo se piden las que faltan, vencieron o fallaron.
    """
    ahora = time.time() if ahora is None else ahora
    firma = str(dias)
    hit, guardado = cache_db.leer(cursor, cuenta_id, CLAVE_VISITAS_ZOMBIES, firma, ttl_segundos=7 * 24 * 3600)
    vigentes = {}
    if hit and isinstance(guardado, dict):
        for id_item, par in guardado.items():
            if isinstance(par, list) and len(par) == 2 and par[0] is not None and ahora - float(par[1]) < TTL_VISITA_SEGUNDOS:
                vigentes[id_item] = par
    pedidos = [i for i in ids_lista if i not in vigentes]
    if pedidos:
        for id_item, visitas in obtener_visitas_items(headers, pedidos, date_from, date_to).items():
            if visitas is not None:                                   # lo que falló no se guarda: se vuelve a intentar la próxima vez
                vigentes[id_item] = [visitas, ahora]
        activas = set(ids_lista)
        cache_db.guardar(cursor, cuenta_id, CLAVE_VISITAS_ZOMBIES, {i: p for i, p in vigentes.items() if i in activas}, firma)
    return {i: (vigentes[i][0] if i in vigentes else None) for i in ids_lista}


def _obtener_cantidad_preguntas(headers, id_meli):
    try:
        resp = meli_http.get("https://api.mercadolibre.com/questions/search", params={"item": id_meli, "limit": 1}, headers=headers, timeout=6)
        if resp.status_code == 200:
            return resp.json().get("total", 0)
    except Exception as e:
        print(f"[Embudo] ⚠️ Error consultando preguntas de {id_meli}: {e}")
    return 0


def detectar_publicaciones_zombie(headers, cuenta_id, cursor, dias=60):
    """Activas con 0 visitas y 0 ventas en `dias` días. Las visitas vienen de la caché compartida (ver visitas_con_cache); qué está activo y qué se vendió se lee siempre de la base."""
    fecha_hasta = hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = (hoy_argentina() - timedelta(days=dias)).strftime("%Y-%m-%d")

    cursor.execute("SELECT id_meli, titulo, thumbnail FROM productos_padre WHERE estado = 'active'")
    activos = cursor.fetchall()
    if not activos:
        return []

    ids_lista = [a[0] for a in activos]
    visitas_por_item = visitas_con_cache(headers, cuenta_id, cursor, ids_lista, fecha_desde, fecha_hasta, dias)

    cursor.execute("SELECT DISTINCT id_meli FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde, fecha_hasta))
    ids_con_venta = {row[0] for row in cursor.fetchall()}

    zombies = []
    for id_meli, titulo, thumbnail in activos:
        if visitas_por_item.get(id_meli) == 0 and id_meli not in ids_con_venta:          # None = no sabemos: no se acusa a la publicación
            zombies.append({"id_meli": id_meli, "titulo": titulo, "thumbnail": thumbnail})
    return zombies


DIAS_EMBUDO = 28     # = las visitas de 14 días + las de los 14 anteriores que ya guarda enriquecimiento.py (sin llamar a la API por publicación)
MIN_VISITAS_PARA_JUZGAR = 100     # con menos visitas, "0 ventas" no dice nada: 17 visitas sin venta es lo normal, no una ficha para revisar
FACTOR_BAJA_CONVERSION = 0.5      # una publicación convierte mal si lo hace a menos de la mitad que el promedio de la propia cuenta
MIN_CONVERSION_REFERENCIA = 0.3   # piso de ese umbral: aunque el promedio de la cuenta sea muy bajo, por debajo de 0,3% se revisa


def diagnosticar(visitas, vendidas, conversion_global):
    """
    "sin_datos" | "pocos_datos" | "revisar_ficha" | "poca_visibilidad" | "funciona_bien". Solo se juzga con visitas suficientes y contra el promedio de la propia
    cuenta (el rubro, el precio y la temporada cambian lo que es una buena conversión: un número fijo para todos no sirve).
    """
    if visitas <= 0:
        return "sin_datos"
    tasa = vendidas / visitas * 100
    if visitas >= MIN_VISITAS_PARA_JUZGAR:
        if tasa < max(conversion_global * FACTOR_BAJA_CONVERSION, MIN_CONVERSION_REFERENCIA):
            return "revisar_ficha"
        return "funciona_bien"
    if vendidas >= 2 and tasa >= max(conversion_global, MIN_CONVERSION_REFERENCIA):
        return "poca_visibilidad"            # vende bien lo poco que se ve: lo que falta son visitas
    return "pocos_datos"


def contar_preguntas_por_publicacion(headers, seller_id, dias):
    """
    {item_id: cantidad de preguntas} de los últimos `dias` días, en pocas llamadas: se listan las preguntas del vendedor (de a 50, de la más
    nueva a la más vieja) hasta pasar la fecha de corte. Antes era una llamada por publicación. None si Mercado Libre no respondió.
    """
    corte = datetime.now().astimezone() - timedelta(days=dias)
    conteo, offset = {}, 0
    while offset < 2000:
        try:
            resp = meli_http.get("https://api.mercadolibre.com/questions/search", headers=headers, timeout=10,
                                 params={"seller_id": seller_id, "limit": 50, "offset": offset, "sort_fields": "date_created", "sort_types": "DESC"})
        except Exception as e:
            print(f"[Embudo] ⚠️ No se pudieron traer las preguntas: {e}")
            return None
        if resp.status_code != 200:
            return None
        pagina = resp.json().get("questions") or []
        for q in pagina:
            try:
                if datetime.fromisoformat(q["date_created"]) < corte:
                    return conteo
            except (KeyError, ValueError):
                continue
            if q.get("item_id"):
                conteo[q["item_id"]] = conteo.get(q["item_id"], 0) + 1
        if len(pagina) < 50:
            break
        offset += 50
    return conteo


def calcular_embudo_conversion(headers, cuenta_id, cursor, dias=DIAS_EMBUDO):
    ahora = time.time()
    cacheado = _cache_embudo.get(cuenta_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    fecha_hasta = hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = (hoy_argentina() - timedelta(days=dias)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.thumbnail, p.precio,
               COALESCE(SUM(v.stock_propio + v.stock_full), 0) AS stock_total, p.visitas_14d, p.visitas_previas_14d
        FROM productos_padre p
        LEFT JOIN productos_variantes v ON v.id_padre = p.id
        WHERE p.estado = 'active'
        GROUP BY p.id_meli, p.titulo, p.thumbnail, p.precio, p.visitas_14d, p.visitas_previas_14d
    """)
    activos = cursor.fetchall()
    if not activos:
        return []

    # Visitas: las guardadas por el enriquecimiento (14 días + los 14 anteriores). Solo lo que todavía no tiene dato se pide a la API.
    visitas_por_item = {a[0]: (a[5] or 0) + (a[6] or 0) for a in activos if a[5] is not None}
    faltan = [a[0] for a in activos if a[5] is None]
    if faltan:
        visitas_por_item.update(obtener_visitas_items(headers, faltan, fecha_desde, fecha_hasta))

    cursor.execute("SELECT id_meli, COALESCE(SUM(cantidad), 0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s GROUP BY id_meli", (fecha_desde, fecha_hasta))
    ventas_por_item = dict(cursor.fetchall())

    cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila_cuenta = cursor.fetchone()
    preguntas_por_item = contar_preguntas_por_publicacion(headers, fila_cuenta[0], dias) if fila_cuenta else None
    if preguntas_por_item is None:
        # Sin el listado completo se cae a la consulta por publicación (más lenta, pero igual de correcta)
        preguntas_por_item = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futuros = {pool.submit(_obtener_cantidad_preguntas, headers, id_meli): id_meli for id_meli, *_resto in activos}
            for futuro in as_completed(futuros):
                id_meli = futuros[futuro]
                try:
                    preguntas_por_item[id_meli] = futuro.result()
                except Exception:
                    preguntas_por_item[id_meli] = 0

    total_visitas = sum((visitas_por_item.get(a[0], 0) or 0) for a in activos)
    total_vendidas = sum(ventas_por_item.get(a[0], 0) for a in activos)
    conversion_global = (total_vendidas / total_visitas * 100) if total_visitas > 0 else 0.0

    resultado = []
    for id_meli, titulo, thumbnail, precio, stock_total, visitas_14d, visitas_previas in activos:
        visitas = visitas_por_item.get(id_meli, 0) or 0
        # Tendencia: las visitas de los últimos 14 días contra los 14 anteriores (las completa enriquecimiento.py en segundo plano);
        # con muy pocas visitas el porcentaje no dice nada
        tendencia = round((visitas_14d - visitas_previas) / visitas_previas * 100) if (visitas_14d is not None and visitas_previas and visitas_previas >= 20) else None
        preguntas = preguntas_por_item.get(id_meli, 0)
        vendidas = ventas_por_item.get(id_meli, 0)
        tasa_conversion = round((vendidas / visitas) * 100, 2) if visitas > 0 else None
        diagnostico = diagnosticar(visitas, vendidas, conversion_global)

        resultado.append({
            "id_meli": id_meli, "titulo": titulo, "visitas": visitas, "preguntas": preguntas,
            "vendidas": vendidas, "tasa_conversion": tasa_conversion, "diagnostico": diagnostico,
            "thumbnail": thumbnail, "precio": float(precio or 0), "stock_total": int(stock_total or 0), "tendencia_visitas": tendencia,
            "conversion_global": round(conversion_global, 2),
        })

    def _prioridad(r):
        if r["diagnostico"] == "revisar_ficha":
            return (0, -r["visitas"])
        if r["diagnostico"] == "poca_visibilidad":
            return (1, -r["visitas"])
        return (2, -r["visitas"])
    resultado.sort(key=_prioridad)

    _cache_embudo[cuenta_id] = {"data": resultado, "timestamp": ahora}
    return resultado

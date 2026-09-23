"""
Sincronizador de VENTAS — este módulo nunca había existido en el port.
sincronizador.py (el que ya estaba) solo trae el catálogo (publicaciones
y stock); acá se traen las ÓRDENES reales de MeLi y se cargan en
`ventas`. Sin esto, ninguna página que dependa de ventas (Ganancia
Real, Dashboard, Despacho, etc.) tenía de dónde sacar datos reales.

Incremental desde el arranque: se guarda hasta qué fecha ya se trajeron
órdenes (`cuentas_meli.ultima_sincronizacion_ventas`) y la próxima vuelta
arranca desde ahí, con un colchón de 2 horas hacia atrás para no perder
una orden por un desfasaje de reloj o huso horario. `ON CONFLICT DO
UPDATE` hace que reprocesar ese colchón sea seguro (no duplica).
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import meli_http
import db

TAMANO_PAGINA = 50
COLCHON_INCREMENTAL_HORAS = 2

# /orders/search de MeLi no deja pedir offset+limit > 1000 en una misma
# búsqueda (rechaza el pedido con 4xx a partir de ahí). Si una ventana de
# fechas tiene más de esto, hay que partirla en dos y pedir cada mitad
# por separado — si no, todo lo que quede después del resultado 1000 se
# pierde en silencio. Con orden date_asc esto significa perder las
# órdenes más RECIENTES del rango, que es justo lo que se vio en
# producción: facturación de los últimos días por debajo de la real.
LIMITE_OFFSET_MELI = 1000
VENTANA_MINIMA = timedelta(minutes=10)

HILOS_COSTO_ENVIO = 8


def _iso(dt):
    # Siempre normalizamos a UTC antes de formatear: el sufijo "-00:00" de
    # abajo asume que los componentes (hora, minuto, ...) ya son UTC. Si
    # alguna vez `dt` llegara con otro tzinfo (ej. si cambia la config de
    # timezone de la conexión a Postgres), sin este .astimezone() el string
    # resultante describiría un instante distinto, corrido por el offset.
    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000-00:00")


def _obtener_pagina_ordenes(access_token, seller_id, fecha_desde, fecha_hasta, offset):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "seller": seller_id, "order.date_created.from": _iso(fecha_desde), "order.date_created.to": _iso(fecha_hasta),
        "sort": "date_asc", "offset": offset, "limit": TAMANO_PAGINA,
    }
    resp = meli_http.get("https://api.mercadolibre.com/orders/search", headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        print(f"[VentasSync] ⚠️ Error trayendo órdenes: {resp.status_code} - {resp.text[:300]}")
        return [], 0
    data = resp.json()
    return data.get("results", []), (data.get("paging", {}) or {}).get("total", 0)


# Vive mientras viva el proceso (el scheduler corre cada 4 minutos sin
# parar), así que necesita un tope — si no, crece para siempre. shipment_id
# es un ID de MeLi único a nivel global (no por cuenta), así que compartir
# este caché entre cuentas no mezcla datos de tenants distintos.
_cache_shipment = {}
LIMITE_CACHE_SHIPMENT = 20000


def _obtener_costo_envio(access_token, shipment_id):
    """
    Costo de envío real cobrado al vendedor. Best-effort a propósito: si
    MeLi todavía no liquidó el costo (pasa seguido con FULL o colecta),
    devolvemos 0 en vez de inventar un número — se puede recalcular
    corriendo el sync de nuevo más adelante, cuando MeLi ya lo haya
    liquidado, gracias a que esto es incremental y reprocesa el colchón.
    Por eso el 0 nunca se guarda en el caché: si se guardara, esa segunda
    pasada (colchón) nunca volvería a consultar MeLi y el costo quedaría
    en 0 clavado para siempre mientras el proceso siga vivo, aunque MeLi
    ya haya liquidado el envío hace rato.
    """
    if shipment_id in _cache_shipment:
        return _cache_shipment[shipment_id]
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}", headers=headers, timeout=8)
        if resp.status_code != 200:
            return 0.0
        data = resp.json()
        costo = (data.get("shipping_option", {}) or {}).get("cost")
        if costo is None:
            costo = data.get("cost_components", {}).get("seller", 0) if isinstance(data.get("cost_components"), dict) else 0
        costo = float(costo or 0.0)
        if costo:
            if len(_cache_shipment) >= LIMITE_CACHE_SHIPMENT:
                _cache_shipment.clear()
            _cache_shipment[shipment_id] = costo
        return costo
    except Exception as e:
        print(f"[VentasSync] ⚠️ Error consultando envío {shipment_id}: {e}")
        return 0.0


def _precargar_costos_envio(ordenes, access_token):
    """
    Antes esto se hacía una orden a la vez, adentro de _extraer_filas_de_orden
    — con cientos/miles de órdenes en el sync inicial, esa cadena de
    llamadas HTTP secuenciales (una por orden) fue la causa real de que la
    primera sincronización tardara varios minutos. Acá se resuelven todos
    los shipment_id nuevos de la página en paralelo (con un pool chico,
    para no pasarnos del rate limit de MeLi) y se dejan en _cache_shipment
    — _extraer_filas_de_orden después los lee del caché, sin red.
    """
    ids_a_pedir = set()
    for orden in ordenes:
        shipment_id = (orden.get("shipping", {}) or {}).get("id")
        if shipment_id and str(shipment_id) not in _cache_shipment:
            ids_a_pedir.add(str(shipment_id))
    if not ids_a_pedir:
        return
    with ThreadPoolExecutor(max_workers=HILOS_COSTO_ENVIO) as pool:
        list(pool.map(lambda sid: _obtener_costo_envio(access_token, sid), ids_a_pedir))


def _extraer_filas_de_orden(orden, access_token):
    """Una orden puede tener más de un ítem — cada uno es una fila de `ventas`."""
    id_orden = str(orden.get("id"))
    status = orden.get("status")
    if status in ("cancelled", "invalid"):
        return []

    fecha_creada_raw = orden.get("date_created", "")
    try:
        fecha_dt = datetime.fromisoformat(fecha_creada_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        fecha_dt = datetime.now(timezone.utc)

    items = orden.get("order_items", []) or []
    if not items:
        return []

    shipping_info = orden.get("shipping", {}) or {}
    shipment_id = shipping_info.get("id")
    costo_envio_total = _obtener_costo_envio(access_token, str(shipment_id)) if shipment_id else 0.0
    facturado_total_orden = sum(float(it.get("unit_price") or 0) * int(it.get("quantity") or 1) for it in items) or 1.0

    buyer = orden.get("buyer", {}) or {}
    filas = []
    for it in items:
        item_info = it.get("item", {}) or {}
        id_meli = item_info.get("id")
        if not id_meli:
            continue
        cantidad = int(it.get("quantity") or 1)
        precio_unitario = float(it.get("unit_price") or 0.0)
        cargo_venta = it.get("sale_fee")
        cargo_venta = float(cargo_venta) if cargo_venta is not None else None

        proporcion = (precio_unitario * cantidad) / facturado_total_orden
        costo_envio_item = round(costo_envio_total * proporcion, 2)

        filas.append({
            "id_orden": id_orden, "id_meli": id_meli, "id_variante": str(item_info.get("variation_id") or ""),
            "titulo": item_info.get("title"), "cantidad": cantidad, "precio_venta": precio_unitario,
            "cargo_venta": cargo_venta, "costo_envio": costo_envio_item,
            "fecha_venta": fecha_dt.date().isoformat(), "hora_venta": fecha_dt.time().strftime("%H:%M:%S"),
            "shipment_id": str(shipment_id) if shipment_id else None,
            "envio_estado": shipping_info.get("status"),
            "despachado": shipping_info.get("status") in ("shipped", "delivered"),
            "comprador_nickname": buyer.get("nickname"), "comprador_nombre": buyer.get("first_name"),
        })
    return filas


def _escribir_pagina(cursor, cuenta_id, ordenes, access_token):
    """Precarga costos de envío en paralelo y hace upsert de la página. Devuelve (ordenes, filas) escritas."""
    _precargar_costos_envio(ordenes, access_token)
    filas_insertadas = 0
    for orden in ordenes:
        for f in _extraer_filas_de_orden(orden, access_token):
            cursor.execute("""
                INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta,
                                     cargo_venta, costo_envio, fecha_venta, hora_venta, shipment_id, envio_estado,
                                     despachado, comprador_nickname, comprador_nombre)
                VALUES (%(cuenta_id)s, %(id_orden)s, %(id_meli)s, %(id_variante)s, %(titulo)s, %(cantidad)s,
                        %(precio_venta)s, %(cargo_venta)s, %(costo_envio)s, %(fecha_venta)s, %(hora_venta)s,
                        %(shipment_id)s, %(envio_estado)s, %(despachado)s, %(comprador_nickname)s, %(comprador_nombre)s)
                ON CONFLICT (cuenta_id, id_orden, id_meli) DO UPDATE SET
                    cantidad = excluded.cantidad, precio_venta = excluded.precio_venta,
                    cargo_venta = COALESCE(excluded.cargo_venta, ventas.cargo_venta),
                    costo_envio = excluded.costo_envio, envio_estado = excluded.envio_estado,
                    despachado = excluded.despachado
            """, {**f, "cuenta_id": cuenta_id})
            filas_insertadas += 1
    return len(ordenes), filas_insertadas


def _sincronizar_rango(usuario_id, cuenta_id, access_token, seller_id, fecha_desde, fecha_hasta):
    """
    Trae y guarda todas las órdenes del rango. Si el rango tiene más de
    LIMITE_OFFSET_MELI resultados, lo parte en dos mitades por fecha y
    procesa cada una por separado en vez de seguir paginando con un offset
    que MeLi va a terminar rechazando (ver comentario de LIMITE_OFFSET_MELI
    arriba). Un pequeño solape en el punto medio es intencional y
    inofensivo: el ON CONFLICT hace que reprocesar la misma orden dos veces
    sea un upsert, no un duplicado.
    """
    _, total = _obtener_pagina_ordenes(access_token, seller_id, fecha_desde, fecha_hasta, 0)

    if total > LIMITE_OFFSET_MELI and (fecha_hasta - fecha_desde) > VENTANA_MINIMA:
        punto_medio = fecha_desde + (fecha_hasta - fecha_desde) / 2
        oa, fa = _sincronizar_rango(usuario_id, cuenta_id, access_token, seller_id, fecha_desde, punto_medio)
        ob, fb = _sincronizar_rango(usuario_id, cuenta_id, access_token, seller_id, punto_medio, fecha_hasta)
        return oa + ob, fa + fb

    if total > LIMITE_OFFSET_MELI:
        print(f"[VentasSync] ⚠️ Cuenta {cuenta_id}: {total} órdenes entre {fecha_desde} y {fecha_hasta} no se pueden traer completas (tope de MeLi) — puede faltar alguna de ese tramo tan angosto.")

    ordenes_procesadas = 0
    filas_insertadas = 0
    offset = 0
    while True:
        ordenes, total = _obtener_pagina_ordenes(access_token, seller_id, fecha_desde, fecha_hasta, offset)
        if not ordenes:
            break

        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            o, f = _escribir_pagina(cursor, cuenta_id, ordenes, access_token)
            ordenes_procesadas += o
            filas_insertadas += f

        offset += TAMANO_PAGINA
        if offset >= total or offset >= LIMITE_OFFSET_MELI:
            break
        time.sleep(0.2)

    return ordenes_procesadas, filas_insertadas


def sincronizar_ventas(usuario_id, cuenta_id, access_token, seller_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT ultima_sincronizacion_ventas FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
        ultima_sync = fila[0] if fila else None

    ahora = datetime.now(timezone.utc)
    if ultima_sync:
        fecha_desde = ultima_sync - timedelta(hours=COLCHON_INCREMENTAL_HORAS)
    else:
        fecha_desde = ahora - timedelta(days=365)

    ordenes_procesadas, filas_insertadas = _sincronizar_rango(usuario_id, cuenta_id, access_token, seller_id, fecha_desde, ahora)

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE cuentas_meli SET ultima_sincronizacion_ventas = %s WHERE id = %s", (ahora, cuenta_id))

    print(f"[VentasSync] ✨ Cuenta {cuenta_id}: {ordenes_procesadas} orden(es), {filas_insertadas} fila(s) de venta sincronizadas.")
    return ordenes_procesadas, filas_insertadas

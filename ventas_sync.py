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
import flex
from utils import ARGENTINA

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
# Provincia de destino — separada del caché de costo porque la dirección
# no cambia con el tiempo (se puede cachear siempre que se consiga, a
# diferencia del costo 0 de abajo, que a propósito NO se cachea).
_cache_provincia_envio = {}
# logistic_type real del envío (drop_off/self_service/fulfillment/...) —
# tampoco cambia con el tiempo una vez despachado, así que se cachea
# siempre que se consiga, igual que la provincia.
_cache_tipo_logistica = {}
# (código postal, localidad, lat, lon) de destino — lo usa flex.py para ubicar el envío y calcular su zona.
_cache_ubicacion_envio = {}
# Costo que Mercado Libre le cobra al VENDEDOR por un envío (GET /shipments/{id}/costs), y datos de cada pago (retenciones, neto
# depositado, fecha de acreditación). Mismo criterio que arriba: un 0 no se cachea (puede ser "todavía no liquidado") y los IDs de
# MeLi son globales, así que compartir estos cachés entre cuentas no mezcla tenants.
_cache_costo_envio_vendedor = {}
_cache_pago = {}
LIMITE_CACHE_SHIPMENT = 20000


def _ubicacion_de_envio(data):
    """(código postal, localidad, latitud, longitud) del destino de un /shipments/{id}, o None si MeLi no informó nada de eso."""
    direccion = (data or {}).get("receiver_address", {}) or {}
    codigo_postal = str(direccion.get("zip_code") or "").strip() or None
    localidad = ((direccion.get("city") or {}).get("name") or (direccion.get("neighborhood") or {}).get("name") or "").strip() or None
    try:
        lat, lon = float(direccion.get("latitude")), float(direccion.get("longitude"))
    except (TypeError, ValueError):
        lat = lon = None
    if lat is not None and lat == 0 and lon == 0:
        lat = lon = None   # MeLi manda 0,0 cuando la dirección no está geolocalizada
    return (codigo_postal, localidad, lat, lon) if (codigo_postal or localidad or lat is not None) else None


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

    De paso deja la provincia del comprador en _cache_provincia_envio —
    mismo recurso /shipments/{id}, así que sale gratis (sin pegarle de
    nuevo a la API).
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

        provincia = ((data.get("receiver_address", {}) or {}).get("state", {}) or {}).get("name")
        if provincia:
            if len(_cache_provincia_envio) >= LIMITE_CACHE_SHIPMENT:
                _cache_provincia_envio.clear()
            _cache_provincia_envio[shipment_id] = provincia

        ubicacion = _ubicacion_de_envio(data)
        if ubicacion:
            if len(_cache_ubicacion_envio) >= LIMITE_CACHE_SHIPMENT:
                _cache_ubicacion_envio.clear()
            _cache_ubicacion_envio[shipment_id] = ubicacion

        tipo_logistica = data.get("logistic_type")
        if tipo_logistica:
            if len(_cache_tipo_logistica) >= LIMITE_CACHE_SHIPMENT:
                _cache_tipo_logistica.clear()
            _cache_tipo_logistica[shipment_id] = tipo_logistica

        if costo:
            if len(_cache_shipment) >= LIMITE_CACHE_SHIPMENT:
                _cache_shipment.clear()
            _cache_shipment[shipment_id] = costo
        return costo
    except Exception as e:
        print(f"[VentasSync] ⚠️ Error consultando envío {shipment_id}: {e}")
        return 0.0


def _costo_envio_vendedor(access_token, shipment_id):
    """
    Lo que Mercado Libre le cobra al VENDEDOR por este envío: GET /shipments/{id}/costs -> senders[0].cost.
    OJO: _obtener_costo_envio guarda shipping_option.cost, que es lo que paga el COMPRADOR (0 si el envío es gratis); usar eso como
    costo de envío hacía que la ganancia saliera ~15% de la facturación por encima de lo depositado (en FULL el envío cuesta ~15%
    de la venta). None si no se pudo saber. Flex no pasa por acá: el costo lo cobra la logística propia (ver flex.py).
    """
    if shipment_id in _cache_costo_envio_vendedor:
        return _cache_costo_envio_vendedor[shipment_id]
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}/costs", headers={"Authorization": f"Bearer {access_token}"}, timeout=8)
        if resp.status_code != 200:
            return None
        costo = float(((resp.json().get("senders") or [{}])[0]).get("cost") or 0.0)
        if costo > 0:
            if len(_cache_costo_envio_vendedor) >= LIMITE_CACHE_SHIPMENT:
                _cache_costo_envio_vendedor.clear()
            _cache_costo_envio_vendedor[shipment_id] = costo
        return costo
    except Exception as e:
        print(f"[VentasSync] ⚠️ Error consultando el costo real del envío {shipment_id}: {e}")
        return None


def _datos_de_pago(access_token, payment_id):
    """
    {"retenciones", "cupones", "neto", "liberacion"} de un pago aprobado, o None. Sale de GET api.mercadopago.com/v1/payments/{id}:
    net_received_amount es lo que MeLi realmente deposita; charges_details desglosa lo descontado y las retenciones de impuestos
    (IIBB, SIRTAC...) son los cargos de tipo "tax"; money_release_date es cuándo se acredita.
    """
    if payment_id in _cache_pago:
        return _cache_pago[payment_id]
    try:
        resp = meli_http.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers={"Authorization": f"Bearer {access_token}"}, timeout=8)
        if resp.status_code != 200:
            return None
        d = resp.json()
        neto = (d.get("transaction_details") or {}).get("net_received_amount")
        if d.get("status") != "approved" or neto is None:
            return None
        def _suma(filtro):
            return sum(float((c.get("amounts") or {}).get("original") or 0) - float((c.get("amounts") or {}).get("refunded") or 0)
                       for c in (d.get("charges_details") or []) if filtro(c))
        retenciones = _suma(lambda c: c.get("type") == "tax")
        # Cupones que financia el VENDEDOR (collector -> ML). Los que financia MeLi van de ML al comprador y no le cuestan nada.
        cupones = _suma(lambda c: c.get("type") == "coupon" and (c.get("accounts") or {}).get("from") == "collector")
        # Costo de ofrecer cuotas que paga el vendedor (ya está dentro del sale_fee / cargo_venta; acá se separa para mostrarlo)
        financiacion = _suma(lambda c: c.get("name") == "financing_add_on_fee" and (c.get("accounts") or {}).get("from") == "collector")
        datos = {"retenciones": round(retenciones, 2), "cupones": round(cupones, 2), "financiacion": round(financiacion, 2), "neto": round(float(neto), 2),
                 "liberacion": (d.get("money_release_date") or "")[:10] or None}
        if len(_cache_pago) >= LIMITE_CACHE_SHIPMENT:
            _cache_pago.clear()
        _cache_pago[payment_id] = datos
        return datos
    except Exception as e:
        print(f"[VentasSync] ⚠️ Error consultando el pago {payment_id}: {e}")
        return None


def _repartir_envios(cursor, cuenta_id, shipment_ids):
    """
    Reparte el costo de cada envío entre las filas de ventas que lo comparten (un envío puede cubrir varias órdenes, y una orden
    varios ítems), en proporción a lo facturado, y deja costo_envio = parte de MeLi + costo_flex. Solo toca filas que ya tienen el
    costo del envío (envio_shipment_total); guarda el valor anterior en costo_envio_original la primera vez.
    """
    ids = [s for s in set(shipment_ids) if s]
    if not ids:
        return
    cursor.execute("""
        WITH t AS (SELECT shipment_id, SUM(precio_venta * cantidad) AS fact FROM ventas
                   WHERE cuenta_id = %(cuenta)s AND shipment_id = ANY(%(ids)s) GROUP BY shipment_id)
        UPDATE ventas v SET
            costo_envio_original = COALESCE(v.costo_envio_original, v.costo_envio),
            costo_envio_meli = COALESCE(ROUND(v.envio_shipment_total * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0),
            costo_envio = COALESCE(ROUND(v.envio_shipment_total * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0) + v.costo_flex
        FROM t
        WHERE v.cuenta_id = %(cuenta)s AND v.shipment_id = t.shipment_id AND v.envio_shipment_total IS NOT NULL AND v.origen = 'meli'
    """, {"cuenta": cuenta_id, "ids": ids})


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
    with ThreadPoolExecutor(max_workers=HILOS_COSTO_ENVIO) as pool:
        if ids_a_pedir:
            list(pool.map(lambda sid: _obtener_costo_envio(access_token, sid), ids_a_pedir))
        # Costo REAL del envío (no Flex) y datos de cada pago: se resuelven en paralelo y _extraer_filas_de_orden los lee del caché
        ids_envio = {str((o.get("shipping") or {}).get("id")) for o in ordenes if (o.get("shipping") or {}).get("id")}
        ids_envio = [s for s in ids_envio if s not in _cache_costo_envio_vendedor and _cache_tipo_logistica.get(s) not in (None, "self_service")]
        if ids_envio:
            list(pool.map(lambda sid: _costo_envio_vendedor(access_token, sid), ids_envio))
        ids_pagos = {p["id"] for o in ordenes if o.get("status") not in ("cancelled", "invalid") for p in (o.get("payments") or []) if p.get("id")} - set(_cache_pago)
        if ids_pagos:
            list(pool.map(lambda pid: _datos_de_pago(access_token, pid), ids_pagos))


def _fecha_hora_argentina(fecha_iso):
    """
    ("YYYY-MM-DD", "HH:MM:SS") en hora argentina de la fecha que informa Mercado Libre. MeLi manda "2026-09-30T23:30:00.000-04:00": el offset es
    -04:00 aunque Argentina es UTC-3, así que tomar la hora tal cual la dejaba una hora atrasada (y una venta de 00:30 caía en el día anterior).
    Sin offset se asume que ya viene en hora argentina; si no se puede leer, se usa el momento actual.
    """
    try:
        dt = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(ARGENTINA) if dt.tzinfo else dt.replace(tzinfo=ARGENTINA)
    return dt.date().isoformat(), dt.time().strftime("%H:%M:%S")


def _extraer_filas_de_orden(orden, access_token):
    """Una orden puede tener más de un ítem — cada uno es una fila de `ventas`."""
    id_orden = str(orden.get("id"))
    status = orden.get("status")
    if status in ("cancelled", "invalid"):
        return []

    fecha_venta, hora_venta = _fecha_hora_argentina(orden.get("date_created", ""))

    items = orden.get("order_items", []) or []
    if not items:
        return []

    shipping_info = orden.get("shipping", {}) or {}
    shipment_id = shipping_info.get("id")
    costo_envio_total = _obtener_costo_envio(access_token, str(shipment_id)) if shipment_id else 0.0
    provincia = _cache_provincia_envio.get(str(shipment_id)) if shipment_id else None
    tipo_logistica = _cache_tipo_logistica.get(str(shipment_id)) if shipment_id else None
    codigo_postal, localidad, destino_lat, destino_lon = (_cache_ubicacion_envio.get(str(shipment_id)) or (None, None, None, None)) if shipment_id else (None, None, None, None)
    facturado_total_orden = sum(float(it.get("unit_price") or 0) * int(it.get("quantity") or 1) for it in items) or 1.0

    # Costo de envío del vendedor para TODO el envío (se reparte después, ver _repartir_envios). Flex: 0, el costo es el de la logística propia.
    if shipment_id and tipo_logistica == "self_service":
        envio_shipment_total = 0.0
    elif shipment_id and tipo_logistica:
        envio_shipment_total = _cache_costo_envio_vendedor.get(str(shipment_id))
    else:
        envio_shipment_total = None

    buyer = orden.get("buyer", {}) or {}
    # Cuotas: la trae cada pago de la orden, no el ítem — si hay más de
    # un pago (poco común en retail chico) nos quedamos con el primero.
    # None si MeLi no informó el dato, para no confundir "no sabemos"
    # con "pagó contado" en los reportes que usan esto.
    pagos = orden.get("payments", []) or []
    cuotas_orden = pagos[0].get("installments") if pagos else None
    # Retenciones, lo que MeLi deposita de verdad y cuándo se acredita: solo si hay datos de TODOS los pagos de la orden
    datos_pagos = [_cache_pago.get(p.get("id")) for p in pagos if p.get("id")]
    if pagos and datos_pagos and all(datos_pagos):
        retenciones_orden = sum(d["retenciones"] for d in datos_pagos)
        cupones_orden = sum(d["cupones"] for d in datos_pagos)
        financiacion_orden = sum(d.get("financiacion") or 0 for d in datos_pagos)
        neto_orden = sum(d["neto"] for d in datos_pagos)
        liberacion = min((d["liberacion"] for d in datos_pagos if d["liberacion"]), default=None)
        pago_id = pagos[0].get("id")
    else:
        retenciones_orden = cupones_orden = financiacion_orden = neto_orden = liberacion = pago_id = None

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
        cupones_item = round(cupones_orden * proporcion, 2) if cupones_orden is not None else None
        financiacion_item = round(financiacion_orden * proporcion, 2) if financiacion_orden is not None else None
        # cargo_venta = TODO lo que MeLi cobra por la venta: comisión + financiación (sale_fee) + cupones que financia el vendedor
        if cargo_venta is not None and cupones_item:
            cargo_venta = round(cargo_venta + cupones_item, 2)
        costo_envio_item = round(costo_envio_total * proporcion, 2)

        filas.append({
            "envio_shipment_total": envio_shipment_total, "pago_id": pago_id, "fecha_liberacion": liberacion, "cupones": cupones_item, "financiacion": financiacion_item,
            "retenciones": round(retenciones_orden * proporcion, 2) if retenciones_orden is not None else None,
            "neto_recibido": round(neto_orden * proporcion, 2) if neto_orden is not None else None,
            "id_orden": id_orden, "id_meli": id_meli, "id_variante": str(item_info.get("variation_id") or ""),
            "titulo": item_info.get("title"), "cantidad": cantidad, "precio_venta": precio_unitario,
            "cargo_venta": cargo_venta, "costo_envio": costo_envio_item,
            "fecha_venta": fecha_venta, "hora_venta": hora_venta,
            "shipment_id": str(shipment_id) if shipment_id else None,
            "envio_estado": shipping_info.get("status"),
            "despachado": shipping_info.get("status") in ("shipped", "delivered"),
            "comprador_nickname": buyer.get("nickname"), "comprador_nombre": buyer.get("first_name"),
            "cuotas": cuotas_orden, "provincia": provincia, "tipo_logistica": tipo_logistica,
            "codigo_postal": codigo_postal, "localidad": localidad, "destino_lat": destino_lat, "destino_lon": destino_lon,
        })
    return filas


def _escribir_pagina(cursor, cuenta_id, ordenes, access_token):
    """Precarga costos de envío en paralelo y hace upsert de la página. Devuelve (ordenes, filas) escritas."""
    _precargar_costos_envio(ordenes, access_token)
    filas_insertadas = 0
    shipments_de_la_pagina = set()
    for orden in ordenes:
        for f in _extraer_filas_de_orden(orden, access_token):
            # costo_envio = lo que informa MeLi + costo_flex (entrega Flex que cargó el usuario, ver flex.py): al
            # reprocesar una orden hay que conservar esa parte, si no el costo Flex se perdería en el próximo sync.
            cursor.execute("""
                INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta,
                                     cargo_venta, costo_envio, fecha_venta, hora_venta, shipment_id, envio_estado,
                                     despachado, comprador_nickname, comprador_nombre, cuotas, provincia, tipo_logistica,
                                     codigo_postal, localidad, destino_lat, destino_lon,
                                     envio_shipment_total, retenciones, neto_recibido, fecha_liberacion, monto_liberacion, pago_id, cupones, financiacion,
                                     hora_normalizada)
                VALUES (%(cuenta_id)s, %(id_orden)s, %(id_meli)s, %(id_variante)s, %(titulo)s, %(cantidad)s,
                        %(precio_venta)s, %(cargo_venta)s, %(costo_envio)s, %(fecha_venta)s, %(hora_venta)s,
                        %(shipment_id)s, %(envio_estado)s, %(despachado)s, %(comprador_nickname)s, %(comprador_nombre)s, %(cuotas)s, %(provincia)s, %(tipo_logistica)s,
                        %(codigo_postal)s, %(localidad)s, %(destino_lat)s, %(destino_lon)s,
                        %(envio_shipment_total)s, %(retenciones)s, %(neto_recibido)s, %(fecha_liberacion)s, %(neto_recibido)s, %(pago_id)s, %(cupones)s, %(financiacion)s,
                        true)
                ON CONFLICT (cuenta_id, id_orden, id_meli) DO UPDATE SET
                    cantidad = excluded.cantidad, precio_venta = excluded.precio_venta,
                    cargo_venta = CASE
                        WHEN excluded.cargo_venta IS NULL THEN ventas.cargo_venta
                        WHEN excluded.cupones IS NOT NULL THEN excluded.cargo_venta   -- ya trae los cupones sumados
                        ELSE excluded.cargo_venta + COALESCE(ventas.cupones, 0) END,   -- sin datos de pago esta vez: se conserva lo que ya había
                    costo_envio = excluded.costo_envio + ventas.costo_flex, envio_estado = excluded.envio_estado,
                    despachado = excluded.despachado, cuotas = COALESCE(excluded.cuotas, ventas.cuotas),
                    provincia = COALESCE(excluded.provincia, ventas.provincia),
                    tipo_logistica = COALESCE(excluded.tipo_logistica, ventas.tipo_logistica),
                    codigo_postal = COALESCE(excluded.codigo_postal, ventas.codigo_postal),
                    localidad = COALESCE(excluded.localidad, ventas.localidad),
                    destino_lat = COALESCE(excluded.destino_lat, ventas.destino_lat),
                    destino_lon = COALESCE(excluded.destino_lon, ventas.destino_lon),
                    envio_shipment_total = COALESCE(excluded.envio_shipment_total, ventas.envio_shipment_total),
                    retenciones = COALESCE(excluded.retenciones, ventas.retenciones),
                    neto_recibido = COALESCE(excluded.neto_recibido, ventas.neto_recibido),
                    monto_liberacion = COALESCE(excluded.monto_liberacion, ventas.monto_liberacion),
                    fecha_liberacion = COALESCE(excluded.fecha_liberacion, ventas.fecha_liberacion),
                    pago_id = COALESCE(excluded.pago_id, ventas.pago_id),
                    cupones = COALESCE(excluded.cupones, ventas.cupones),
                    financiacion = COALESCE(excluded.financiacion, ventas.financiacion)
            """, {**f, "cuenta_id": cuenta_id})
            filas_insertadas += 1
            if f["shipment_id"]:
                shipments_de_la_pagina.add(f["shipment_id"])
    _repartir_envios(cursor, cuenta_id, shipments_de_la_pagina)
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

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            o, f = _escribir_pagina(cursor, cuenta_id, ordenes, access_token)
            ordenes_procesadas += o
            filas_insertadas += f

        offset += TAMANO_PAGINA
        if offset >= total or offset >= LIMITE_OFFSET_MELI:
            break
        time.sleep(0.2)

    return ordenes_procesadas, filas_insertadas


DIAS_COMPLETAR_LOGISTICA = 540
TOPE_COMPLETAR_LOGISTICA = 40
# Datos que MeLi no supo informar: no se reintentan en cada pasada (si no, los mismos 40 tapan a los que sí se pueden completar).
# shipment_id / id de orden son IDs globales de MeLi, no de una cuenta, así que compartir estos sets no mezcla tenants.
_logistica_sin_dato = set()
_pago_sin_dato = set()


def _completar_datos_de_envio(usuario_id, cuenta_id, access_token, dias=DIAS_COMPLETAR_LOGISTICA, tope=TOPE_COMPLETAR_LOGISTICA):
    """
    Completa en ventas viejas el tipo de logística, el destino (código postal, localidad, coordenadas) y el COSTO REAL del envío.
    Se guardan al sincronizar la orden, pero el sync incremental solo reprocesa las últimas horas: las anteriores a las migraciones
    0012 / 0019 / 0022 no tienen esos datos. De a `tope` envíos por pasada, los más nuevos primero. Best-effort — nunca rompe el sync.
    Devuelve cuántos envíos se completaron.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT shipment_id FROM ventas
                WHERE cuenta_id = %s AND origen = 'meli' AND shipment_id IS NOT NULL AND fecha_venta >= current_date - %s
                  AND (tipo_logistica IS NULL OR (tipo_logistica = 'self_service' AND destino_lat IS NULL) OR envio_shipment_total IS NULL)
                GROUP BY shipment_id ORDER BY MAX(fecha_venta) DESC LIMIT %s
            """, (cuenta_id, dias, tope + len(_logistica_sin_dato)))
            pendientes = [r[0] for r in cursor.fetchall() if r[0] not in _logistica_sin_dato][:tope]
        if not pendientes:
            return 0

        headers = {"Authorization": f"Bearer {access_token}"}

        def _datos_de(shipment_id):
            try:
                resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}", headers=headers, timeout=8)
                if resp.status_code != 200:
                    return shipment_id, None, None, None
                data = resp.json()
                tipo = data.get("logistic_type")
                costo = None
                if tipo and tipo != "self_service":
                    costo = _costo_envio_vendedor(access_token, shipment_id)
                return shipment_id, tipo, _ubicacion_de_envio(data), costo
            except Exception:
                return shipment_id, None, None, None

        with ThreadPoolExecutor(max_workers=HILOS_COSTO_ENVIO) as pool:
            resultados = list(pool.map(_datos_de, pendientes))

        completados, con_costo = 0, []
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for shipment_id, tipo, ubicacion, costo in resultados:
                if not tipo and not ubicacion:
                    if len(_logistica_sin_dato) >= LIMITE_CACHE_SHIPMENT:
                        _logistica_sin_dato.clear()
                    _logistica_sin_dato.add(shipment_id)
                    continue
                codigo_postal, localidad, destino_lat, destino_lon = ubicacion or (None, None, None, None)
                # Flex: 0 (el costo es el de la logística propia). Los demás: el costo real que informó MeLi, o nada si no se pudo saber.
                envio_total = 0.0 if tipo == "self_service" else costo
                cursor.execute("""
                    UPDATE ventas SET tipo_logistica = COALESCE(tipo_logistica, %s),
                                      codigo_postal = COALESCE(codigo_postal, %s), localidad = COALESCE(localidad, %s),
                                      destino_lat = COALESCE(destino_lat, %s), destino_lon = COALESCE(destino_lon, %s),
                                      envio_shipment_total = COALESCE(envio_shipment_total, %s)
                    WHERE cuenta_id = %s AND shipment_id = %s
                """, (tipo, codigo_postal, localidad, destino_lat, destino_lon, envio_total, cuenta_id, shipment_id))
                if envio_total is not None:
                    con_costo.append(shipment_id)
                elif tipo:
                    _logistica_sin_dato.add(shipment_id)   # tiene tipo pero MeLi no informó el costo: no insistir en cada pasada
                completados += 1
            _repartir_envios(cursor, cuenta_id, con_costo)
        return completados
    except Exception as e:
        print(f"[VentasSync] ⚠️ No se pudo completar los datos de envío de ventas viejas: {e}")
        return 0


def _completar_datos_de_pago(usuario_id, cuenta_id, access_token, dias=DIAS_COMPLETAR_LOGISTICA, tope=30):
    """
    Completa en ventas viejas lo que MeLi realmente depositó (neto), las retenciones de impuestos y la fecha de acreditación.
    Dos consultas por orden (la orden para saber sus pagos, y el pago), de a `tope` órdenes por pasada, las más nuevas primero.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT id_orden FROM ventas
                WHERE cuenta_id = %s AND origen = 'meli' AND neto_recibido IS NULL AND fecha_venta >= current_date - %s
                GROUP BY id_orden ORDER BY MAX(fecha_venta) DESC LIMIT %s
            """, (cuenta_id, dias, tope + len(_pago_sin_dato)))
            pendientes = [r[0] for r in cursor.fetchall() if r[0] not in _pago_sin_dato][:tope]
        if not pendientes:
            return 0

        headers = {"Authorization": f"Bearer {access_token}"}

        def _datos_de(id_orden):
            try:
                resp = meli_http.get(f"https://api.mercadolibre.com/orders/{id_orden}", headers=headers, timeout=8)
                if resp.status_code != 200:
                    return id_orden, None
                pagos = [p["id"] for p in (resp.json().get("payments") or []) if p.get("id")]
                datos = [_datos_de_pago(access_token, p) for p in pagos]
                return id_orden, ((pagos, datos) if pagos and all(datos) else None)
            except Exception:
                return id_orden, None

        with ThreadPoolExecutor(max_workers=HILOS_COSTO_ENVIO) as pool:
            resultados = list(pool.map(_datos_de, pendientes))

        completados = 0
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for id_orden, res in resultados:
                if not res:
                    if len(_pago_sin_dato) >= LIMITE_CACHE_SHIPMENT:
                        _pago_sin_dato.clear()
                    _pago_sin_dato.add(id_orden)
                    continue
                pagos, datos = res
                liberacion = min((d["liberacion"] for d in datos if d["liberacion"]), default=None)
                cursor.execute("""
                    UPDATE ventas v SET
                        cargo_venta = CASE WHEN v.cargo_venta IS NULL THEN NULL
                                      ELSE v.cargo_venta - COALESCE(v.cupones, 0) + COALESCE(ROUND(%(cup)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0) END,
                        cupones = COALESCE(ROUND(%(cup)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0),
                        financiacion = COALESCE(ROUND(%(fin)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0),
                        retenciones = ROUND(%(reten)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2),
                        neto_recibido = ROUND(%(neto)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2),
                        monto_liberacion = ROUND(%(neto)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2),
                        fecha_liberacion = %(lib)s, pago_id = %(pago)s
                    FROM (SELECT id_orden, SUM(precio_venta * cantidad) AS fact FROM ventas WHERE cuenta_id = %(cuenta)s AND id_orden = %(orden)s GROUP BY id_orden) t
                    WHERE v.cuenta_id = %(cuenta)s AND v.id_orden = t.id_orden
                """, {"cup": sum(d["cupones"] for d in datos), "fin": sum(d.get("financiacion") or 0 for d in datos), "reten": sum(d["retenciones"] for d in datos), "neto": sum(d["neto"] for d in datos), "lib": liberacion,
                      "pago": pagos[0], "cuenta": cuenta_id, "orden": id_orden})
                completados += 1
        return completados
    except Exception as e:
        print(f"[VentasSync] ⚠️ No se pudo completar los datos de pago de ventas viejas: {e}")
        return 0


_financiacion_sin_dato = set()


def _completar_financiacion(usuario_id, cuenta_id, access_token, dias=DIAS_COMPLETAR_LOGISTICA, tope=30):
    """
    Separa el cargo de financiación (lo que cuesta ofrecer cuotas) en las ventas que ya tenían su pago guardado antes de que existiera
    esta columna. Una consulta por orden, de a `tope` por pasada, las más nuevas primero. Ya está dentro de cargo_venta: no cambia la ganancia.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT id_orden, MIN(pago_id) FROM ventas
                WHERE cuenta_id = %s AND origen = 'meli' AND financiacion IS NULL AND pago_id IS NOT NULL AND fecha_venta >= current_date - %s
                GROUP BY id_orden ORDER BY MAX(fecha_venta) DESC LIMIT %s
            """, (cuenta_id, dias, tope + len(_financiacion_sin_dato)))
            pendientes = [(o, p) for o, p in cursor.fetchall() if o not in _financiacion_sin_dato][:tope]
        if not pendientes:
            return 0
        with ThreadPoolExecutor(max_workers=HILOS_COSTO_ENVIO) as pool:
            resultados = list(pool.map(lambda op: (op[0], _datos_de_pago(access_token, op[1])), pendientes))
        completados = 0
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for id_orden, datos in resultados:
                if not datos:
                    if len(_financiacion_sin_dato) >= LIMITE_CACHE_SHIPMENT:
                        _financiacion_sin_dato.clear()
                    _financiacion_sin_dato.add(id_orden)
                    continue
                cursor.execute("""
                    UPDATE ventas v SET financiacion = COALESCE(ROUND(%(fin)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0)
                    FROM (SELECT id_orden, SUM(precio_venta * cantidad) AS fact FROM ventas WHERE cuenta_id = %(cuenta)s AND id_orden = %(orden)s GROUP BY id_orden) t
                    WHERE v.cuenta_id = %(cuenta)s AND v.id_orden = t.id_orden
                """, {"fin": datos.get("financiacion") or 0, "cuenta": cuenta_id, "orden": id_orden})
                completados += 1
        return completados
    except Exception as e:
        print(f"[VentasSync] ⚠️ No se pudo completar el cargo de financiación de ventas viejas: {e}")
        return 0


def _ids_ordenes_canceladas(access_token, seller_id, desde=None):
    """
    IDs de las órdenes canceladas en Mercado Libre. Con `desde`, solo las que CAMBIARON desde esa fecha (order.date_last_updated):
    el sync pide las órdenes por fecha de creación, así que una orden creada hace 8 días y cancelada hoy no se volvía a ver nunca.
    Devuelve None si Mercado Libre no respondió (no se sabe: no se retira nada).
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    ids, offset = [], 0
    while True:
        params = {"seller": seller_id, "order.status": "cancelled", "sort": "date_desc", "offset": offset, "limit": TAMANO_PAGINA}
        if desde:
            params["order.date_last_updated.from"] = _iso(desde)
        try:
            resp = meli_http.get("https://api.mercadolibre.com/orders/search", headers=headers, params=params, timeout=15)
        except Exception as e:
            print(f"[VentasSync] ⚠️ No se pudo consultar las órdenes canceladas: {e}")
            return None
        if resp.status_code != 200:
            print(f"[VentasSync] ⚠️ Órdenes canceladas: {resp.status_code} - {resp.text[:200]}")
            return None
        resultados = resp.json().get("results") or []
        ids += [str(o["id"]) for o in resultados if o.get("id")]
        offset += TAMANO_PAGINA
        if len(resultados) < TAMANO_PAGINA or offset >= LIMITE_OFFSET_MELI:
            return ids


def retirar_ventas_canceladas(usuario_id, cuenta_id, access_token, seller_id, desde=None):
    """
    Saca de `ventas` las filas de órdenes que Mercado Libre ya tiene canceladas o reembolsadas (el sync nunca guarda una orden
    cancelada, pero una que estaba paga y se cancela después seguía sumando a facturación y ganancia). La fila completa queda
    archivada en `ventas_retiradas` (JSON), así que no se pierde nada. Devuelve cuántas filas retiró.
    """
    ids = _ids_ordenes_canceladas(access_token, seller_id, desde)
    if not ids:
        return 0
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            WITH retiradas AS (
                DELETE FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND id_orden = ANY(%s) RETURNING *
            )
            INSERT INTO ventas_retiradas (cuenta_id, id_orden, motivo, monto, fila)
            SELECT cuenta_id, id_orden, 'cancelada', precio_venta * cantidad, to_jsonb(retiradas) FROM retiradas
        """, (cuenta_id, ids))
        return cursor.rowcount


def sincronizar_ventas(usuario_id, cuenta_id, access_token, seller_id):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
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

    # Órdenes que se cancelaron o reembolsaron desde la última sincronización: dejan de contar como venta. En la primera
    # sincronización no hay nada que retirar (las canceladas nunca se guardan).
    if ultima_sync:
        try:
            retiradas = retirar_ventas_canceladas(usuario_id, cuenta_id, access_token, seller_id, desde=fecha_desde)
            if retiradas:
                print(f"[VentasSync] ↩️ Cuenta {cuenta_id}: {retiradas} venta(s) cuya orden se canceló o reembolsó se retiraron del cálculo.")
        except Exception as e:
            print(f"[VentasSync] ⚠️ No se pudieron retirar las ventas canceladas: {e}")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE cuentas_meli SET ultima_sincronizacion_ventas = %s WHERE id = %s", (ahora, cuenta_id))

    completados = _completar_datos_de_envio(usuario_id, cuenta_id, access_token)
    if completados:
        print(f"[VentasSync] 🚚 Cuenta {cuenta_id}: completé los datos de envío de {completados} venta(s) anteriores.")
    _completar_financiacion(usuario_id, cuenta_id, access_token)
    pagos_completados = _completar_datos_de_pago(usuario_id, cuenta_id, access_token)
    if pagos_completados:
        print(f"[VentasSync] 💵 Cuenta {cuenta_id}: completé lo depositado y las retenciones de {pagos_completados} orden(es) anteriores.")

    # Flex: a cada envío nuevo se le aplica el umbral que le corresponde según su zona de Mercado Libre. Las zonas
    # (y el domicilio de salida) se refrescan una vez por semana, solo en cuentas que ya usan Flex.
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            config = flex.obtener_config(cursor, cuenta_id)
            if flex.sincronizacion_vieja(config["info"]):
                cursor.execute("SELECT COUNT(*) FROM ventas WHERE cuenta_id = %s AND tipo_logistica = 'self_service'", (cuenta_id,))
                if (cursor.fetchone()[0] or 0) > 0:
                    flex.sincronizar_con_meli(cursor, cuenta_id, access_token, seller_id)
            aplicadas = flex.aplicar_automatico(cursor, cuenta_id)
        if aplicadas:
            print(f"[VentasSync] 🚚 Cuenta {cuenta_id}: {aplicadas} envío(s) Flex con su costo de entrega aplicado.")
    except Exception as e:
        print(f"[VentasSync] ⚠️ No se pudo aplicar el costo de entrega Flex: {e}")

    print(f"[VentasSync] ✨ Cuenta {cuenta_id}: {ordenes_procesadas} orden(es), {filas_insertadas} fila(s) de venta sincronizadas.")
    return ordenes_procesadas, filas_insertadas

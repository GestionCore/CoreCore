"""
Sincronizador de catálogo — portado de Santi Mens.

Cambios reales (no cosméticos):
1. `_candado_sincro` era un Lock ÚNICO para todo el proceso — con una
   sola cuenta esto evitaba sincronizaciones simultáneas de ESA cuenta,
   pero en multi-tenant hubiera bloqueado a la cuenta B mientras la
   cuenta A está sincronizando, sin ninguna relación entre ellas. Ahora
   es un lock por cuenta_id.
2. `productos_variantes.id_padre` ahora apunta a la clave propia
   (productos_padre.id), no al id_meli de texto — así que escribir un
   ítem primero hace upsert de productos_padre con RETURNING id, y usa
   ese id recién obtenido para las variantes.
3. Los avisos por WhatsApp quedan comentados (sin puente todavía).
"""
import re
import threading
from datetime import datetime
import requests
import meli_http
import validacion_meli
import db
import ventas_sync
from auth import token_manager

_candados_por_cuenta = {}
_candado_de_candados = threading.Lock()


def _obtener_candado(cuenta_id):
    with _candado_de_candados:
        if cuenta_id not in _candados_por_cuenta:
            _candados_por_cuenta[cuenta_id] = threading.Lock()
        return _candados_por_cuenta[cuenta_id]


def _extraer_talle_color(variante_data, titulo=""):
    talle = "Único"
    color = "Único"
    for attr in variante_data.get("attribute_combinations", []):
        nombre_attr = attr.get("name", "")
        valor_attr = attr.get("value_name")
        if not valor_attr:
            continue
        if nombre_attr in ("Talle", "Size"):
            talle = valor_attr
        elif nombre_attr == "Color":
            color = valor_attr

    if talle == "Único" and titulo:
        match_talle = re.search(r'\b(XXXL|XXL|XL|L|M|S|\d+)\b', titulo, re.IGNORECASE)
        if match_talle:
            talle = match_talle.group(0).upper()

    return talle, color


def _consultar_precio_original(id_item, headers):
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_item}/sale_price", headers=headers, params={"context": "channel_marketplace"}, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("regular_amount")
    except Exception as e:
        print(f"[Sincronizador] ⚠️ No se pudo consultar sale_price de {id_item}: {e}")
    return None


def _consultar_recibis_estimado(id_item, precio_actual, listing_type_id, site_id, headers):
    if not precio_actual or not listing_type_id:
        return None
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/sites/{site_id}/listing_prices", headers=headers, params={"price": precio_actual}, timeout=5)
        if resp.status_code == 200:
            opciones = resp.json()
            match = next((o for o in opciones if o.get("listing_type_id") == listing_type_id), None)
            if match and match.get("sale_fee_amount") is not None:
                return round(precio_actual - match["sale_fee_amount"], 2)
    except Exception as e:
        print(f"[Sincronizador] ⚠️ No se pudo consultar comisión de {id_item}: {e}")
    return None


def _obtener_datos_item(id_item, headers):
    resp_detalle = meli_http.get(f"https://api.mercadolibre.com/items/{id_item}", headers=headers, timeout=10)
    if resp_detalle.status_code != 200:
        print(f"[Sincronizador] ⚠️ No se pudo traer el detalle de {id_item}: {resp_detalle.status_code}")
        return None

    p = resp_detalle.json()
    precio_actual = p.get("price")
    listing_type_id = p.get("listing_type_id")
    site_id = id_item[:3] if len(id_item) >= 3 else "MLA"

    precio_original = _consultar_precio_original(id_item, headers)
    recibis_estimado = _consultar_recibis_estimado(id_item, precio_actual, listing_type_id, site_id, headers)

    return {"id_item": id_item, "detalle": p, "precio_original": precio_original, "recibis_estimado": recibis_estimado}


def _consultar_stock_convivencia(user_product_id, headers):
    if not user_product_id:
        return None, None
    try:
        resp = requests.get(f"https://api.mercadolibre.com/user-products/{user_product_id}/stock", headers=headers, timeout=6)
        if resp.status_code != 200:
            return None, None
        propio, full = None, None
        for loc in resp.json().get("locations", []):
            if loc.get("type") == "selling_address":
                propio = loc.get("quantity", 0)
            elif loc.get("type") == "meli_facility":
                full = loc.get("quantity", 0)
        return propio, full
    except Exception as e:
        print(f"[Sincronizador] ⚠️ Error consultando stock de convivencia para {user_product_id}: {e}")
        return None, None


def _escribir_item_en_db(cuenta_id, datos, cursor):
    id_item = datos["id_item"]
    p = datos["detalle"]
    titulo = p.get("title")
    nuevo_estado = p.get("status")
    thumbnail = p.get("secure_thumbnail") or p.get("thumbnail")
    precio_actual = p.get("price")

    cuotas = p.get("installments") or {}
    cuotas_cantidad = cuotas.get("quantity") if cuotas.get("quantity", 0) > 1 else None
    cuotas_monto = cuotas.get("amount") if cuotas_cantidad else None

    cursor.execute("SELECT estado, precio FROM productos_padre WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, id_item))
    fila_anterior = cursor.fetchone()
    estado_anterior = fila_anterior[0] if fila_anterior else None
    precio_anterior = float(fila_anterior[1]) if fila_anterior and fila_anterior[1] is not None else None

    if estado_anterior == 'active' and nuevo_estado != 'active':
        print(f"[Sincronizador] ⚠️ '{titulo}' cambió a estado {nuevo_estado.upper()} (aviso por WhatsApp pendiente hasta portar el puente).")

    if precio_anterior is not None and precio_actual is not None and abs(precio_anterior - precio_actual) > 0.01:
        cursor.execute("""
            INSERT INTO historial_precios (cuenta_id, id_meli, precio_anterior, precio_nuevo, fecha_cambio)
            VALUES (%s, %s, %s, %s, now())
        """, (cuenta_id, id_item, precio_anterior, precio_actual))

    cursor.execute("""
        INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, tipo_logistica, thumbnail, precio_original, recibis_estimado, cuotas_cantidad, cuotas_monto)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, id_meli) DO UPDATE SET
            titulo = excluded.titulo, precio = excluded.precio,
            estado = excluded.estado, tipo_logistica = excluded.tipo_logistica,
            thumbnail = excluded.thumbnail, precio_original = excluded.precio_original,
            recibis_estimado = excluded.recibis_estimado,
            cuotas_cantidad = excluded.cuotas_cantidad, cuotas_monto = excluded.cuotas_monto
        RETURNING id
    """, (cuenta_id, id_item, titulo, precio_actual, nuevo_estado, p.get("shipping", {}).get("logistic_type"),
          thumbnail, datos["precio_original"], datos["recibis_estimado"], cuotas_cantidad, cuotas_monto))
    id_padre_interno = cursor.fetchone()[0]

    variantes = p.get("variations", [])
    tipo_logistica = validacion_meli.campo_seguro(p, "shipping.logistic_type", default=None, tipo_esperado=str, contexto=f"item {id_item}")
    es_full = (tipo_logistica == "fulfillment")
    stock_convivencia = datos.get("stock_convivencia")
    es_convivencia = stock_convivencia is not None
    stock_convivencia_propio, stock_convivencia_full = stock_convivencia if stock_convivencia else (None, None)

    lista_vars = variantes if len(variantes) > 0 else [{"id": id_item + "_unica", "available_quantity": p.get("available_quantity", 0)}]

    for v in lista_vars:
        id_var = str(v.get("id"))
        qty_meli = int(v.get("available_quantity", 0))
        talle_var, color_var = _extraer_talle_color(v, titulo=titulo)

        cursor.execute("SELECT stock_propio, stock_full FROM productos_variantes WHERE cuenta_id = %s AND id_variante = %s", (cuenta_id, id_var))
        stock_anterior = cursor.fetchone()
        stock_propio_previo = stock_anterior[0] if stock_anterior else 0
        stock_full_previo = stock_anterior[1] if stock_anterior else 0

        if es_convivencia and stock_convivencia_propio is not None:
            stock_propio = stock_convivencia_propio
            stock_full = stock_convivencia_full or 0
        elif es_full:
            stock_full = qty_meli
            stock_propio = stock_propio_previo
        else:
            stock_propio = qty_meli
            stock_full = 0

        stock_total = stock_propio + stock_full
        stock_total_previo = stock_propio_previo + stock_full_previo

        if stock_anterior and stock_total_previo > 0 and stock_total == 0:
            print(f"[Sincronizador] 📦 '{titulo}' (Talle {talle_var}) se quedó sin stock (aviso por WhatsApp pendiente).")

        cursor.execute("""
            INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, talle, color, stock_propio, stock_full)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (cuenta_id, id_variante) DO UPDATE SET
                id_padre = excluded.id_padre, talle = excluded.talle, color = excluded.color,
                stock_propio = excluded.stock_propio, stock_full = excluded.stock_full
        """, (cuenta_id, id_var, id_padre_interno, talle_var, color_var, stock_propio, stock_full))


def sincronizar_item_individual(cuenta_id, id_item, headers, cursor):
    """Usado por el webhook para actualizar UN solo ítem en tiempo real."""
    datos = _obtener_datos_item(id_item, headers)
    if datos is None:
        return
    _escribir_item_en_db(cuenta_id, datos, cursor)


def sincronizar_catalogo(usuario_id, cuenta_id):
    candado = _obtener_candado(cuenta_id)
    if not candado.acquire(blocking=False):
        print(f"[Sincronizador] ⏳ Ya hay una sincronización corriendo para la cuenta {cuenta_id}. Saltando...")
        return

    try:
        try:
            access_token = token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            return

        with db.conexion_usuario(usuario_id) as conexion_lookup:
            cursor_lookup = conexion_lookup.cursor()
            cursor_lookup.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
            fila = cursor_lookup.fetchone()
        if not fila:
            return
        user_id = fila[0]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Antes esto era una sola llamada con limit=100 y sin offset — traía
        # siempre los mismos primeros 100 ítems de /items/search sin importar
        # cuántas veces se corriera el sync. Si la cuenta tiene más de 100
        # publicaciones (muy probable con variantes de talle/color), el resto
        # nunca se sincronizaba: por eso "modelos activos" quedaba clavado en
        # el mismo número sin importar cuántas veces se le diera a
        # "Sincronizar Todo". /items/search también topea el offset en 1000
        # (igual que /orders/search) — un catálogo más grande que eso
        # necesitaría la API de scroll, que queda fuera de este alcance.
        lista_ids = []
        offset_items = 0
        LIMITE_PAGINA_ITEMS = 100
        while True:
            resp_search = meli_http.get(
                f"https://api.mercadolibre.com/users/{user_id}/items/search",
                headers=headers, params={"limit": LIMITE_PAGINA_ITEMS, "offset": offset_items}, timeout=8
            )
            if resp_search.status_code != 200:
                break
            data_search = resp_search.json()
            resultados = data_search.get("results", [])
            if not resultados:
                break
            lista_ids.extend(resultados)
            total_items = (data_search.get("paging", {}) or {}).get("total", 0)
            offset_items += LIMITE_PAGINA_ITEMS
            if offset_items >= total_items or offset_items >= 1000:
                if total_items > 1000:
                    print(f"[Sincronizador] ⚠️ Cuenta {cuenta_id}: {total_items} publicaciones supera el tope de paginación de MeLi (1000) — quedan {total_items - 1000} sin sincronizar.")
                break
        if not lista_ids:
            return

        items_procesados = []
        lote_size = 20

        for i in range(0, len(lista_ids), lote_size):
            lote = lista_ids[i:i + lote_size]
            ids_param = ",".join(lote)

            resp_batch = meli_http.get(f"https://api.mercadolibre.com/items?ids={ids_param}", headers=headers, timeout=10)
            if resp_batch.status_code != 200:
                continue

            for res in resp_batch.json():
                if res.get("code") == 200 and "body" in res:
                    p = res["body"]
                    tipo_logistica = validacion_meli.campo_seguro(p, "shipping.logistic_type", default=None, tipo_esperado=str, contexto=f"item {p.get('id')}")
                    shipping_tags = validacion_meli.campo_seguro(p, "shipping.tags", default=[], tipo_esperado=list, contexto=f"item {p.get('id')}")
                    es_convivencia = (tipo_logistica == "fulfillment") and "self_service_in" in shipping_tags
                    stock_convivencia = None
                    if es_convivencia:
                        user_product_id = validacion_meli.campo_seguro(p, "user_product_id", default=None, tipo_esperado=str, contexto=f"item {p.get('id')}")
                        if user_product_id:
                            stock_convivencia = _consultar_stock_convivencia(user_product_id, headers)

                    items_procesados.append({
                        "id_item": p.get("id"), "detalle": p, "precio_original": p.get("original_price"),
                        "recibis_estimado": None, "stock_convivencia": stock_convivencia
                    })

        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            for datos in items_procesados:
                _escribir_item_en_db(cuenta_id, datos, cursor)

        print(f"[Sincronizador] ✨ Cuenta {cuenta_id}: {len(items_procesados)}/{len(lista_ids)} ítems sincronizados.")

        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("UPDATE cuentas_meli SET ultima_sincronizacion = now() WHERE id = %s", (cuenta_id,))

    except Exception as e:
        print(f"❌ [Error Sincronizador] cuenta {cuenta_id}: {e}")
    finally:
        candado.release()


def sincronizar_todo(usuario_id, cuenta_id):
    """
    Catálogo + Ventas en una sola pasada — esto es lo que corre el botón
    "Sincronizar Todo", el arranque automático de la primera vez, y la
    tarea periódica. Al terminar, marca `sincronizacion_inicial_completa`
    en true (si no lo estaba ya) — es la bandera que el frontend usa para
    saber si ya puede mostrar datos reales o todavía tiene que mostrar la
    pantalla de "estamos trayendo tu información".
    """
    try:
        access_token = token_manager.asegurar_token_valido(cuenta_id)
    except token_manager.CuentaDesconectada:
        return

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
    if not fila:
        return
    seller_id = fila[0]

    sincronizar_catalogo(usuario_id, cuenta_id)

    try:
        ventas_sync.sincronizar_ventas(usuario_id, cuenta_id, access_token, seller_id)
    except Exception as e:
        print(f"❌ [Error VentasSync] cuenta {cuenta_id}: {e}")

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE cuentas_meli SET sincronizacion_inicial_completa = true WHERE id = %s AND sincronizacion_inicial_completa = false", (cuenta_id,))

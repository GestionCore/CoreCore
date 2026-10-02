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
import threading
from concurrent.futures import ThreadPoolExecutor
import meli_http
import validacion_meli
import db
import ventas_sync
import capacidades
import enriquecimiento
from utils import extraer_talle

LOTE_MULTIGET_MELI = 20
import devoluciones_sync
from antirrebote import Antirrebote
from auth import token_manager

# Una venta dispara varias notificaciones seguidas: se juntan en una sola sincronización por cuenta cada 15 segundos
_antirrebote_webhook = Antirrebote(15)

_candados_por_cuenta = {}
_candado_de_candados = threading.Lock()


def _obtener_candado(cuenta_id):
    with _candado_de_candados:
        if cuenta_id not in _candados_por_cuenta:
            _candados_por_cuenta[cuenta_id] = threading.Lock()
        return _candados_por_cuenta[cuenta_id]


def _extraer_talle_color(variante_data, titulo="", atributos_item=None):
    """
    Talle y color de una variante. Para el talle, de más a menos confiable: el atributo de la variación, el atributo SIZE del ítem
    (lo que Mercado Libre trae para ropa, calzado, etc.) y por último lo que parece un talle en el título (utils.extraer_talle).
    Un ítem de un rubro sin talles queda en "Único".
    """
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

    if talle == "Único":
        talle_item = next((a.get("value_name") for a in (atributos_item or []) if a.get("id") == "SIZE" and a.get("value_name")), None)
        talle = extraer_talle(titulo, talle_item)

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
        resp = meli_http.get(f"https://api.mercadolibre.com/user-products/{user_product_id}/stock", headers=headers, timeout=6)
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
        INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, tipo_logistica, thumbnail, precio_original, recibis_estimado, cuotas_cantidad, cuotas_monto,
                                     catalog_product_id, inventory_id, permalink, category_id, listing_type_id, user_product_id, family_id, sub_estado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, id_meli) DO UPDATE SET
            titulo = excluded.titulo, precio = excluded.precio,
            estado = excluded.estado, tipo_logistica = excluded.tipo_logistica,
            thumbnail = excluded.thumbnail, precio_original = excluded.precio_original,
            recibis_estimado = excluded.recibis_estimado,
            cuotas_cantidad = excluded.cuotas_cantidad, cuotas_monto = excluded.cuotas_monto,
            catalog_product_id = excluded.catalog_product_id, inventory_id = excluded.inventory_id, permalink = excluded.permalink,
            category_id = excluded.category_id, listing_type_id = excluded.listing_type_id,
            user_product_id = excluded.user_product_id, family_id = excluded.family_id, sub_estado = excluded.sub_estado
        RETURNING id
    """, (cuenta_id, id_item, titulo, precio_actual, nuevo_estado, p.get("shipping", {}).get("logistic_type"),
          thumbnail, datos["precio_original"], datos["recibis_estimado"], cuotas_cantidad, cuotas_monto,
          p.get("catalog_product_id"), p.get("inventory_id"), p.get("permalink"), p.get("category_id"), p.get("listing_type_id"),
          p.get("user_product_id"), str(p["family_id"]) if p.get("family_id") else None, ",".join(p.get("sub_status") or [])))
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
        talle_var, color_var = _extraer_talle_color(v, titulo=titulo, atributos_item=p.get("attributes"))

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


def procesar_notificacion_webhook(topic, resource, meli_user_id):
    """
    Punto de entrada real del webhook de MeLi (/notificaciones_meli en
    app.py) — se llama en un hilo de fondo, después de que la ruta ya
    respondió 200. MeLi espera esa respuesta casi inmediata; si tarda
    o falla seguido, reintenta y eventualmente puede deshabilitar las
    notificaciones para la app entera, así que acá adentro NUNCA debe
    reventar: todo queda envuelto y solo se loguea.

    Todavía no hay sesión de usuario en este punto (es MeLi pegándole
    a la API, no un browser logueado) — por eso arranca por el canal
    admin, lo mismo que hace registro.py, solo para ENCONTRAR de qué
    cuenta se trata a partir de meli_user_id. En cuanto se sabe el
    usuario_id, se pasa al canal normal con RLS para cualquier
    escritura real.
    """
    if not meli_user_id or not topic:
        return
    try:
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE meli_user_id = %s AND activa = true", (meli_user_id,))
            fila = cursor.fetchone()
        if not fila:
            return
        cuenta_id, usuario_id = fila

        try:
            access_token = token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            return

        if topic == "items":
            id_item = (resource or "").rsplit("/", 1)[-1]
            if not id_item:
                return
            headers = {"Authorization": f"Bearer {access_token}"}

            def _item():
                with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                    sincronizar_item_individual(cuenta_id, id_item, headers, conexion.cursor())
            _antirrebote_webhook.ejecutar((cuenta_id, "item", id_item), _item)

        elif topic in ("orders_v2", "orders", "shipments"):
            # Reusa el mismo sync incremental que corre cada 4 minutos —
            # trae desde ultima_sincronizacion_ventas con su colchón de 2hs,
            # así que llamarlo de más (webhook + scheduler solapados) es
            # seguro, no duplica nada gracias al ON CONFLICT DO UPDATE.
            # Los cambios de un envío (despachado, entregado) llegan por esta misma vía.
            _antirrebote_webhook.ejecutar((cuenta_id, "ventas"), lambda: ventas_sync.sincronizar_ventas(usuario_id, cuenta_id, access_token, meli_user_id))

        elif topic == "questions":
            _antirrebote_webhook.ejecutar((cuenta_id, "preguntas"), lambda: devoluciones_sync.sincronizar_preguntas(usuario_id, cuenta_id, access_token, meli_user_id))

        elif topic in ("claims", "post_purchase"):
            _antirrebote_webhook.ejecutar((cuenta_id, "reclamos"), lambda: devoluciones_sync.sincronizar_reclamos(usuario_id, cuenta_id, access_token, meli_user_id))

        # Otros topics (payments, messages, etc.) no tienen sync propio — se ignoran a propósito en vez de fallar.

    except Exception as e:
        print(f"❌ [Webhook] Error procesando notificación (topic={topic}, resource={resource}): {e}")


LIMITE_PAGINA_ITEMS = 100
TOPE_OFFSET_MELI = 1000          # /users/{id}/items/search no pagina por offset más allá de 1000 resultados
MAX_PAGINAS_SCAN = 500           # 50.000 publicaciones: un corte de seguridad contra un scroll que no termina


def listar_ids_publicaciones(user_id, headers, cuenta_id=None, get=None):
    """
    Los ids de TODAS las publicaciones del vendedor. Hasta 1000 se pagina por offset; con más, Mercado Libre exige el modo `scan` con
    `scroll_id` (antes el sync cortaba en 1000 y el resto de las publicaciones nunca se sincronizaba). `get` es meli_http.get (se inyecta en las pruebas).
    """
    get = get or meli_http.get
    url = f"https://api.mercadolibre.com/users/{user_id}/items/search"
    ids, offset, total = [], 0, 0
    while True:
        resp = get(url, headers=headers, params={"limit": LIMITE_PAGINA_ITEMS, "offset": offset}, timeout=8)
        if resp.status_code != 200:
            break
        data = resp.json()
        resultados = data.get("results", [])
        if not resultados:
            break
        ids.extend(resultados)
        total = (data.get("paging", {}) or {}).get("total", 0)
        offset += LIMITE_PAGINA_ITEMS
        if offset >= total or offset >= TOPE_OFFSET_MELI:
            break
    if total <= TOPE_OFFSET_MELI:
        return ids

    # Más de 1000: scan + scroll_id desde cero (el scroll devuelve todo, sin tope)
    print(f"[Sincronizador] ℹ️ Cuenta {cuenta_id}: {total} publicaciones, más que el tope de paginación (1000): se usa el modo scan.")
    vistos, ordenados, scroll_id = set(), [], None
    for _ in range(MAX_PAGINAS_SCAN):
        params = {"search_type": "scan", "limit": LIMITE_PAGINA_ITEMS}
        if scroll_id:
            params["scroll_id"] = scroll_id
        resp = get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[Sincronizador] ⚠️ Cuenta {cuenta_id}: el modo scan falló ({resp.status_code}); se usan las {len(ids)} ya obtenidas por offset.")
            return ids
        data = resp.json()
        nuevos = [i for i in data.get("results", []) if i not in vistos]
        if not nuevos:
            break
        vistos.update(nuevos)
        ordenados.extend(nuevos)
        scroll_id = data.get("scroll_id") or scroll_id
    return ordenados or ids


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

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion_lookup:
            cursor_lookup = conexion_lookup.cursor()
            cursor_lookup.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
            fila = cursor_lookup.fetchone()
        if not fila:
            return
        user_id = fila[0]
        headers = {"Authorization": f"Bearer {access_token}"}

        lista_ids = listar_ids_publicaciones(user_id, headers, cuenta_id)
        if not lista_ids:
            return

        items_procesados = []
        pendientes_convivencia = []  # (índice en items_procesados, user_product_id)
        # MeLi limita GET /items?ids= a 20 ids por pedido (con más responde 400 "only allows 20 elements"). Con lotes de 50 el sync
        # de catálogo fallaba entero y en silencio: no se actualizaba ningún precio, stock ni estado ("0/83 ítems sincronizados").
        lote_size = LOTE_MULTIGET_MELI

        for i in range(0, len(lista_ids), lote_size):
            lote = lista_ids[i:i + lote_size]
            ids_param = ",".join(lote)

            resp_batch = meli_http.get(f"https://api.mercadolibre.com/items?ids={ids_param}", headers=headers, timeout=10)
            if resp_batch.status_code != 200:
                print(f"[Sincronizador] ⚠️ Cuenta {cuenta_id}: MeLi rechazó un lote de {len(lote)} ítems ({resp_batch.status_code}): {resp_batch.text[:160]}")
                continue

            for res in resp_batch.json():
                if res.get("code") == 200 and "body" in res:
                    p = res["body"]
                    tipo_logistica = validacion_meli.campo_seguro(p, "shipping.logistic_type", default=None, tipo_esperado=str, contexto=f"item {p.get('id')}")
                    shipping_tags = validacion_meli.campo_seguro(p, "shipping.tags", default=[], tipo_esperado=list, contexto=f"item {p.get('id')}")
                    es_convivencia = (tipo_logistica == "fulfillment") and "self_service_in" in shipping_tags

                    items_procesados.append({
                        "id_item": p.get("id"), "detalle": p, "precio_original": p.get("original_price"),
                        "recibis_estimado": None, "stock_convivencia": None
                    })
                    if es_convivencia:
                        user_product_id = validacion_meli.campo_seguro(p, "user_product_id", default=None, tipo_esperado=str, contexto=f"item {p.get('id')}")
                        if user_product_id:
                            pendientes_convivencia.append((len(items_procesados) - 1, user_product_id))

        # Las consultas de stock de convivencia son independientes entre
        # sí — se resuelven todas en paralelo al final en vez de una por
        # una intercaladas con la descarga de los lotes (mismo patrón que
        # ya se usa en ads.py/metricas.py/despacho.py).
        if pendientes_convivencia:
            with ThreadPoolExecutor(max_workers=8) as pool:
                resultados_convivencia = list(pool.map(
                    lambda item: _consultar_stock_convivencia(item[1], headers), pendientes_convivencia
                ))
            for (indice, _), stock_convivencia in zip(pendientes_convivencia, resultados_convivencia):
                items_procesados[indice]["stock_convivencia"] = stock_convivencia

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for datos in items_procesados:
                _escribir_item_en_db(cuenta_id, datos, cursor)

        print(f"[Sincronizador] ✨ Cuenta {cuenta_id}: {len(items_procesados)}/{len(lista_ids)} ítems sincronizados.")

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("UPDATE cuentas_meli SET ultima_sincronizacion = now() WHERE id = %s", (cuenta_id,))

    except Exception as e:
        print(f"❌ [Error Sincronizador] cuenta {cuenta_id}: {e}")
    finally:
        candado.release()


_sincronizando = set()
_candado_sincronizando = threading.Lock()


def sincronizacion_en_curso(cuenta_id):
    """¿Hay una sincronización completa corriendo AHORA para esta cuenta (en este proceso)?"""
    return cuenta_id in _sincronizando


MINUTOS_SYNC_ATASCADA = 10     # sin nada corriendo después de tanto tiempo: la primera sincronización no está avanzando
MINUTOS_SYNC_LENTA = 25        # corriendo, pero mucho más de lo habitual


def diagnostico_sync_inicial(minutos, en_curso, cuenta_desconectada):
    """
    Cómo viene la PRIMERA sincronización, para decirle a quien espera algo útil en vez de dejar el mismo cartel para siempre:
    "normal", "lenta" (sigue trabajando), "atascada" (nada corre: se reintenta sola cada 4 minutos pero conviene ofrecer reintentar ya) o
    "desconectada" (Mercado Libre retiró el permiso: hay que reconectar, esperar no sirve).
    """
    if cuenta_desconectada:
        return "desconectada"
    if not en_curso and minutos >= MINUTOS_SYNC_ATASCADA:
        return "atascada"
    if minutos >= MINUTOS_SYNC_LENTA:
        return "lenta"
    return "normal"


def sincronizar_todo(usuario_id, cuenta_id):
    """Corre la sincronización completa de la cuenta; si ya hay una en curso no arranca otra (devuelve False)."""
    with _candado_sincronizando:
        if cuenta_id in _sincronizando:
            return False
        _sincronizando.add(cuenta_id)
    try:
        _sincronizar_todo_interno(usuario_id, cuenta_id)
        return True
    finally:
        with _candado_sincronizando:
            _sincronizando.discard(cuenta_id)


def _sincronizar_todo_interno(usuario_id, cuenta_id):
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

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
    if not fila:
        return
    seller_id = fila[0]

    # Si el catálogo falla (red, MeLi, base) las ventas igual se sincronizan, pero la cuenta NO se marca como completa: así la próxima pasada
    # (4 minutos) lo reintenta en vez de mostrarle pantallas sin publicaciones a quien recién se conectó.
    catalogo_ok = True
    try:
        sincronizar_catalogo(usuario_id, cuenta_id)
    except Exception as e:
        catalogo_ok = False
        print(f"❌ [Error Catálogo] cuenta {cuenta_id}: {e}")

    try:
        ventas_sync.sincronizar_ventas(usuario_id, cuenta_id, access_token, seller_id)
    except Exception as e:
        print(f"❌ [Error VentasSync] cuenta {cuenta_id}: {e}")

    # Reclamos/devoluciones y preguntas sin responder — antes esto no
    # tenía sync real, así que Reclamos (en Ganancia Real), Logros y
    # Salud de Cuenta quedaban vacíos para siempre con una cuenta real.
    # Cada mitad ya maneja sus propios errores adentro, así que un
    # problema acá nunca debe frenar el resto de sincronizar_todo.
    devoluciones_sync.sincronizar_posventa(usuario_id, cuenta_id, access_token, seller_id)

    # Qué usa esta cuenta (FULL, Flex, catálogo, publicidad) y los datos extra de cada publicación (calidad, visitas, FULL, catálogo).
    # Es un extra: ningún error de acá puede frenar el resto del sync.
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            capacidades_cuenta = capacidades.refrescar_si_hace_falta(conexion.cursor(), cuenta_id, access_token, seller_id)
        enriquecimiento.refrescar_todo(usuario_id, cuenta_id, access_token, capacidades_cuenta)
    except Exception as e:
        print(f"❌ [Capacidades/Enriquecimiento] cuenta {cuenta_id}: {e}")

    if not catalogo_ok:
        return
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE cuentas_meli SET sincronizacion_inicial_completa = true WHERE id = %s AND sincronizacion_inicial_completa = false", (cuenta_id,))

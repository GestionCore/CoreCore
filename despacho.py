"""
Despacho — portado de Santi Mens. El truco de "sumar horas de offset y
comparar la fecha resultante" para armar la ventana de corte usaba la
sintaxis de fechas de SQLite (date(datetime(...), '+N hours')). En
Postgres se arma sumando un INTERVAL directamente sobre el timestamp
combinado de fecha_venta + hora_venta.
"""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from psycopg.rows import dict_row
import db
import meli_http
from utils import limpiar_titulo_modelo, extraer_talle


def _tipo_envio_legible(tipo_logistica):
    """self_service es Flex; todo lo demás (drop_off, xd_drop_off, cross_docking,
    not_specified o sin dato todavía) es Correo/Mercado Envíos estándar desde
    la perspectiva de "quién tiene que despachar esto" — fulfillment (FULL) ya
    se filtra antes, ni siquiera llega acá."""
    return "Flex" if tipo_logistica == "self_service" else "Correo"


def _limite_de_despacho(sla):
    """
    GET /shipments/{id}/sla → {"status": "on_time" | "delayed" | ..., "expected_date": "2026-10-01T23:00:00-03:00"}: hasta cuándo
    hay que entregar el paquete (al correo o a la logística Flex) para cumplir el plazo que Mercado Libre le prometió al comprador.
    Devuelve (texto, tono) o (None, None) si MeLi no informó fecha.
    """
    try:
        limite = datetime.fromisoformat(sla.get("expected_date"))
    except (TypeError, ValueError, AttributeError):
        return None, None
    ahora = datetime.now(limite.tzinfo)
    dias = (limite.date() - ahora.date()).days
    hora = limite.strftime("%H:%M")
    texto = f"hoy {hora}" if dias == 0 else (f"mañana {hora}" if dias == 1 else f"{limite.strftime('%d/%m')} {hora}")
    if sla.get("status") == "delayed" or limite < ahora:
        return "vencido" if limite < ahora else texto, "danger"
    return texto, ("warn" if dias <= 0 else "info")


def obtener_paquetes_del_dia(usuario_id, cuenta_id, access_token, fecha, offset_horas):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT v.id_orden, v.id_meli, v.id_variante, v.titulo, v.cantidad, v.despachado,
                   v.comprador_nickname, v.comprador_nombre, p.thumbnail, v.shipment_id, v.tipo_logistica, v.flex_zona, v.flex_zona_meli
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE (v.fecha_venta + COALESCE(v.hora_venta, '00:00'::time) + (%s || ' hours')::interval)::date = %s
              AND COALESCE(v.tipo_logistica, p.tipo_logistica, '') != 'fulfillment'
              AND v.origen = 'meli'
            ORDER BY v.despachado ASC, v.id ASC
        """, (offset_horas, fecha))
        filas = cursor.fetchall()

        paquetes = []
        shipment_ids_del_dia = []
        a_verificar = []

        for fila in filas:
            id_orden, id_meli, id_variante, titulo, cantidad, despachado, comprador_nickname, comprador_nombre, thumbnail, shipment_id, tipo_logistica = (
                fila["id_orden"], fila["id_meli"], fila["id_variante"], fila["titulo"], fila["cantidad"], fila["despachado"],
                fila["comprador_nickname"], fila["comprador_nombre"], fila["thumbnail"], fila["shipment_id"], fila["tipo_logistica"]
            )
            talle = extraer_talle(titulo)
            modelo = limpiar_titulo_modelo(titulo)
            clave = f"{id_orden}-{id_meli}-{id_variante}"
            paquetes.append({
                "clave": clave, "id_orden": id_orden, "id_meli": id_meli, "id_variante": id_variante,
                "modelo": modelo, "talle": talle, "cantidad": cantidad, "despachado": bool(despachado),
                "comprador_nickname": comprador_nickname, "comprador_nombre": comprador_nombre,
                "thumbnail": thumbnail, "etiqueta_impresa": False, "tipo_envio": _tipo_envio_legible(tipo_logistica),
                "flex_zona": fila["flex_zona"], "flex_zona_meli": fila["flex_zona_meli"]
            })
            if shipment_id and shipment_id not in shipment_ids_del_dia:
                shipment_ids_del_dia.append(shipment_id)
            # Se re-verifica contra MeLi si todavía no sabemos el estado real
            # (no despachado) o si todavía no sabemos el tipo de logística real
            # de este envío en particular (venta sincronizada antes de que
            # empezáramos a guardar este dato) — en ambos casos hace falta el
            # mismo GET a /shipments/{id}, así que se resuelve junto.
            if shipment_id and (not despachado or tipo_logistica is None):
                a_verificar.append((clave, id_orden, id_meli, id_variante, shipment_id))

        # Las consultas GET son independientes entre sí, así que se
        # paralelizan (mismo patrón que ads.py/metricas.py) — con 30-50
        # pendientes en un día de mucho movimiento, hacerlas una por una
        # tardaba 10-15s en cargar la pantalla que se abre todos los días.
        if a_verificar and access_token:
            headers_shipment = {"Authorization": f"Bearer {access_token}", "x-format-new": "true"}
            paquetes_por_clave = {p["clave"]: p for p in paquetes}

            def _verificar_envio(item):
                clave, id_orden, id_meli, id_variante, shipment_id = item
                try:
                    resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}", headers=headers_shipment, timeout=6)
                    if resp.status_code != 200:
                        return None
                    info_envio = resp.json()
                    sla = None
                    if info_envio.get("status") not in ("shipped", "delivered", "not_delivered", "cancelled"):
                        resp_sla = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}/sla", headers=headers_shipment, timeout=6)
                        sla = resp_sla.json() if resp_sla.status_code == 200 else None
                    return (clave, id_orden, id_meli, id_variante, shipment_id, info_envio.get("status"), info_envio.get("substatus"), info_envio.get("logistic_type"), sla)
                except Exception as e:
                    print(f"[Despacho] ⚠️ No se pudo verificar el envío {shipment_id}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=8) as pool:
                resultados = list(pool.map(_verificar_envio, a_verificar))

            for resultado in resultados:
                if resultado is None:
                    continue
                clave, id_orden, id_meli, id_variante, shipment_id, status, substatus, tipo_logistica_real, sla = resultado
                paquete = paquetes_por_clave[clave]
                if sla:
                    paquete["limite_texto"], paquete["limite_tono"] = _limite_de_despacho(sla)
                if status in ("shipped", "delivered", "not_delivered"):
                    cursor.execute(
                        "UPDATE ventas SET despachado = true WHERE cuenta_id = %s AND id_orden = %s AND id_meli = %s AND id_variante = %s",
                        (cuenta_id, id_orden, id_meli, id_variante)
                    )
                    paquete["despachado"] = True
                elif substatus == "printed":
                    paquete["etiqueta_impresa"] = True

                if tipo_logistica_real:
                    cursor.execute(
                        "UPDATE ventas SET tipo_logistica = %s WHERE cuenta_id = %s AND id_orden = %s AND id_meli = %s AND id_variante = %s AND tipo_logistica IS NULL",
                        (tipo_logistica_real, cuenta_id, id_orden, id_meli, id_variante)
                    )
                    if tipo_logistica_real == "fulfillment":
                        # Ground truth del propio envío: es FULL de verdad,
                        # aunque el catálogo tuviera otra cosa cacheada. MeLi
                        # lo despacha solo, no es una tarea de acá.
                        del paquetes_por_clave[clave]
                    else:
                        paquete["tipo_envio"] = _tipo_envio_legible(tipo_logistica_real)

            paquetes = list(paquetes_por_clave.values())

    total = len(paquetes)
    listos = sum(1 for p in paquetes if p["despachado"])
    tiene_flex = any(p["tipo_envio"] == "Flex" for p in paquetes)
    return paquetes, total, listos, len(shipment_ids_del_dia), tiene_flex


def obtener_shipment_ids_del_dia(usuario_id, fecha, offset_horas, cuenta_id=None):
    """
    Versión liviana de obtener_paquetes_del_dia, para cuando lo único
    que hace falta son los shipment_id del día (descargar etiquetas) —
    sin la verificación de estado contra MeLi que hace la otra función
    (esa sí pega un GET por cada envío pendiente, innecesario acá).
    Mismo filtro WHERE que la otra, para que sea el mismo conjunto de
    envíos en las dos pantallas.
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT DISTINCT v.shipment_id
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE (v.fecha_venta + COALESCE(v.hora_venta, '00:00'::time) + (%s || ' hours')::interval)::date = %s
              AND COALESCE(p.tipo_logistica, '') != 'fulfillment'
              AND v.origen = 'meli'
              AND v.shipment_id IS NOT NULL
        """, (offset_horas, fecha))
        return [r[0] for r in cursor.fetchall()]

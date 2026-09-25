"""
Despacho — portado de Santi Mens. El truco de "sumar horas de offset y
comparar la fecha resultante" para armar la ventana de corte usaba la
sintaxis de fechas de SQLite (date(datetime(...), '+N hours')). En
Postgres se arma sumando un INTERVAL directamente sobre el timestamp
combinado de fecha_venta + hora_venta.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from psycopg.rows import dict_row
import db
import meli_http
from utils import limpiar_titulo_modelo


def obtener_paquetes_del_dia(usuario_id, cuenta_id, access_token, fecha, offset_horas):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT v.id_orden, v.id_meli, v.id_variante, v.titulo, v.cantidad, v.despachado,
                   v.comprador_nickname, v.comprador_nombre, p.thumbnail, v.shipment_id
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE (v.fecha_venta + COALESCE(v.hora_venta, '00:00'::time) + (%s || ' hours')::interval)::date = %s
              AND COALESCE(p.tipo_logistica, '') != 'fulfillment'
              AND v.origen = 'meli'
            ORDER BY v.despachado ASC, v.id ASC
        """, (offset_horas, fecha))
        filas = cursor.fetchall()

        paquetes = []
        shipment_ids_del_dia = []
        pendientes_a_verificar = []

        for fila in filas:
            id_orden, id_meli, id_variante, titulo, cantidad, despachado, comprador_nickname, comprador_nombre, thumbnail, shipment_id = (
                fila["id_orden"], fila["id_meli"], fila["id_variante"], fila["titulo"], fila["cantidad"], fila["despachado"],
                fila["comprador_nickname"], fila["comprador_nombre"], fila["thumbnail"], fila["shipment_id"]
            )
            match_talle = re.search(r'\b(XXXL|XXL|XL|L|M|S|\d+)\b', titulo, re.IGNORECASE)
            talle = match_talle.group(0).upper() if match_talle else "Único"
            modelo = limpiar_titulo_modelo(titulo)
            clave = f"{id_orden}-{id_meli}-{id_variante}"
            paquetes.append({
                "clave": clave, "id_orden": id_orden, "id_meli": id_meli, "id_variante": id_variante,
                "modelo": modelo, "talle": talle, "cantidad": cantidad, "despachado": bool(despachado),
                "comprador_nickname": comprador_nickname, "comprador_nombre": comprador_nombre,
                "thumbnail": thumbnail, "etiqueta_impresa": False
            })
            if shipment_id and shipment_id not in shipment_ids_del_dia:
                shipment_ids_del_dia.append(shipment_id)
            if not despachado and shipment_id:
                pendientes_a_verificar.append((clave, id_orden, id_meli, id_variante, shipment_id))

        # Cruzamos el estado real del envío en MeLi para los pendientes —
        # si ya está shipped/delivered o la etiqueta figura impresa, es
        # porque ya se despachó de verdad y el sistema no se enteró.
        # Las consultas GET son independientes entre sí, así que se
        # paralelizan (mismo patrón que ads.py/metricas.py) — con 30-50
        # pendientes en un día de mucho movimiento, hacerlas una por una
        # tardaba 10-15s en cargar la pantalla que se abre todos los días.
        if pendientes_a_verificar and access_token:
            headers_shipment = {"Authorization": f"Bearer {access_token}", "x-format-new": "true"}
            paquetes_por_clave = {p["clave"]: p for p in paquetes}

            def _verificar_envio(item):
                clave, id_orden, id_meli, id_variante, shipment_id = item
                try:
                    resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}", headers=headers_shipment, timeout=6)
                    if resp.status_code != 200:
                        return None
                    info_envio = resp.json()
                    return (clave, id_orden, id_meli, id_variante, shipment_id, info_envio.get("status"), info_envio.get("substatus"))
                except Exception as e:
                    print(f"[Despacho] ⚠️ No se pudo verificar el envío {shipment_id}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=8) as pool:
                resultados = list(pool.map(_verificar_envio, pendientes_a_verificar))

            for resultado in resultados:
                if resultado is None:
                    continue
                clave, id_orden, id_meli, id_variante, shipment_id, status, substatus = resultado
                if status in ("shipped", "delivered", "not_delivered"):
                    cursor.execute(
                        "UPDATE ventas SET despachado = true WHERE cuenta_id = %s AND id_orden = %s AND id_meli = %s AND id_variante = %s",
                        (cuenta_id, id_orden, id_meli, id_variante)
                    )
                    paquetes_por_clave[clave]["despachado"] = True
                elif substatus == "printed":
                    paquetes_por_clave[clave]["etiqueta_impresa"] = True

    total = len(paquetes)
    listos = sum(1 for p in paquetes if p["despachado"])
    return paquetes, total, listos, len(shipment_ids_del_dia)


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

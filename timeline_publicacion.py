"""Línea de Tiempo de una publicación — portado de Santi Mens."""
import meli_http


def _fecha_str(valor):
    if valor is None:
        return None
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    return str(valor)[:10]


def obtener_fecha_creacion(access_token, id_meli):
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, timeout=8)
        if resp.status_code == 200:
            fecha = resp.json().get("date_created")
            return fecha[:10] if fecha else None
    except Exception as e:
        print(f"[Timeline] ⚠️ Error trayendo fecha de creación: {e}")
    return None


def obtener_timeline(cursor, id_meli, access_token=None):
    eventos = []

    if access_token:
        fecha_creacion = obtener_fecha_creacion(access_token, id_meli)
        if fecha_creacion:
            eventos.append({"fecha": fecha_creacion, "tipo": "creacion", "icono": "🆕", "texto": "Publicación creada"})

    cursor.execute("SELECT precio_anterior, precio_nuevo, fecha_cambio FROM historial_precios WHERE id_meli = %s ORDER BY fecha_cambio", (id_meli,))
    for precio_anterior, precio_nuevo, fecha_cambio in cursor.fetchall():
        precio_anterior, precio_nuevo = float(precio_anterior), float(precio_nuevo)
        direccion = "subió" if precio_nuevo > precio_anterior else "bajó"
        eventos.append({
            "fecha": _fecha_str(fecha_cambio), "tipo": "precio", "icono": "💲",
            "texto": f"Precio {direccion}: ${precio_anterior:,.2f} → ${precio_nuevo:,.2f}"
        })

    cursor.execute("""
        SELECT fecha_venta, cantidad, precio_venta, id_orden FROM ventas
        WHERE id_meli = %s ORDER BY fecha_venta
    """, (id_meli,))
    for fecha_venta, cantidad, precio_venta, id_orden in cursor.fetchall():
        eventos.append({
            "fecha": _fecha_str(fecha_venta), "tipo": "venta", "icono": "🛒",
            "texto": f"Venta: {cantidad} u. a ${float(precio_venta):,.2f} (orden #{id_orden})"
        })

    cursor.execute("""
        SELECT i.fecha, i.tipo, i.motivo, i.monto_retenido FROM incidencias_posventa i
        JOIN ventas v ON v.id_orden = i.id_orden AND v.cuenta_id = i.cuenta_id
        WHERE v.id_meli = %s GROUP BY i.id_reclamo, i.fecha, i.tipo, i.motivo, i.monto_retenido ORDER BY i.fecha
    """, (id_meli,))
    for fecha, tipo, motivo, monto in cursor.fetchall():
        etiqueta = "Cancelación" if "cancel" in (tipo or "").lower() else ("Devolución" if "return" in (tipo or "").lower() or "devol" in (tipo or "").lower() else "Reclamo")
        monto_texto = f" (${float(monto):,.2f} en juego)" if monto else ""
        eventos.append({
            "fecha": _fecha_str(fecha), "tipo": "incidencia", "icono": "⚠️",
            "texto": f"{etiqueta}: {(motivo or '').replace('_', ' ').capitalize()}{monto_texto}"
        })

    eventos.sort(key=lambda e: e["fecha"])
    return eventos

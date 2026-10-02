"""
Registro de ventas por fuera de Mercado Libre (mostrador, canal directo,
Instagram, etc.) — item #2 del brainstorm original, nunca se había
construido.

Reusa la tabla `ventas` tal cual, en vez de crear una tabla aparte —
así una venta manual entra a Ganancia Real, al Dashboard y a los
consolidados por modelo exactamente igual que una venta real de MeLi,
sin duplicar lógica en ningún lado. Lo único que la distingue es la
columna `origen` ('meli' | 'manual'), que además sirve para que
Despacho las excluya (una venta de mostrador ya está entregada, no
necesita etiqueta de envío).

Requiere la migración `ALTER TABLE ventas ADD COLUMN origen TEXT NOT
NULL DEFAULT 'meli';` — ver schema/01_schema_multitenant.sql.
"""
import uuid
from datetime import datetime
from psycopg.rows import dict_row
import db
import stock_meli
from auth import token_manager
from utils import formatear_moneda, ARGENTINA

AVISO_FULL = "Esa publicación está en FULL: su stock lo maneja Mercado Libre, así que el descuento quedó solo en CoreLux."


def _aviso_sin_descontar(motivo):
    return (f"Se registró la venta, pero no pudimos descontar el stock en Mercado Libre ({motivo}) "
            "Descontalo vos ahí para no seguir ofreciendo una unidad que ya no tenés.")


def _en_full(fila):
    """Lo que está en FULL (o convive con FULL) lo maneja Mercado Libre: no se escribe su stock."""
    return fila["tipo_logistica"] == "fulfillment" or bool(fila["inventory_id"])


def obtener_catalogo_para_selector(usuario_id, cuenta_id):
    """Variantes activas con stock propio, para el <select> del formulario."""
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT pv.id_variante, pp.id_meli, pp.titulo, pv.talle, pv.color, pv.stock_propio, pp.precio
            FROM productos_variantes pv
            JOIN productos_padre pp ON pp.id = pv.id_padre AND pp.cuenta_id = pv.cuenta_id
            WHERE pv.cuenta_id = %s AND pp.estado = 'active'
            ORDER BY pp.titulo, pv.talle
        """, (cuenta_id,))
        filas = cursor.fetchall()

    return [{
        "id_variante": f["id_variante"], "id_meli": f["id_meli"],
        "etiqueta": f"{f['titulo']} — {f['talle']}" + (f" / {f['color']}" if f["color"] and f["color"] != "Único" else "") + f" (stock: {f['stock_propio']})",
        "precio_sugerido": float(f["precio"] or 0),
    } for f in filas]


def registrar_venta_manual(usuario_id, cuenta_id, id_variante, cantidad, precio_venta, fecha_venta, comprador_nombre, descontar_en_meli=False):
    """
    Devuelve (ok, error_o_None, aviso_o_None). Con `descontar_en_meli` el stock también se descuenta en Mercado Libre (si no, la sincronización de
    4 minutos pisa el descuento local y la publicación sigue ofreciendo una unidad que ya no hay). Si eso falla la venta igual se registra: ya ocurrió.
    """
    try:
        cantidad = int(cantidad or 0)
        precio_venta = float(precio_venta or 0)
    except (TypeError, ValueError):
        return False, "Cantidad y precio tienen que ser números.", None
    if cantidad <= 0 or precio_venta <= 0:
        return False, "Cantidad y precio tienen que ser mayores a cero.", None

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT pv.id_variante, pp.id_meli, pp.titulo, pp.tipo_logistica, pp.inventory_id
            FROM productos_variantes pv
            JOIN productos_padre pp ON pp.id = pv.id_padre AND pp.cuenta_id = pv.cuenta_id
            WHERE pv.cuenta_id = %s AND pv.id_variante = %s
        """, (cuenta_id, id_variante))
        variante = cursor.fetchone()
        if not variante:
            return False, "Esa variante no pertenece a tu catálogo.", None

        id_orden_manual = f"MANUAL-{uuid.uuid4().hex[:12]}"
        ahora = datetime.now(ARGENTINA)       # la hora de la venta es la argentina, no la del servidor (UTC)
        cursor.execute("""
            INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta,
                                 cargo_venta, costo_envio, fecha_venta, hora_venta, despachado,
                                 comprador_nombre, origen)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s, true, %s, 'manual')
            RETURNING id
        """, (
            cuenta_id, id_orden_manual, variante["id_meli"], variante["id_variante"], variante["titulo"],
            cantidad, precio_venta, fecha_venta, ahora.time(), comprador_nombre or None
        ))
        id_venta = cursor.fetchone()["id"]

        # Igual que una venta real: descuenta del stock propio disponible.
        # GREATEST evita que quede en negativo si el stock cargado ya
        # estaba desactualizado — mejor mostrar 0 que un número raro.
        cursor.execute(
            "UPDATE productos_variantes SET stock_propio = GREATEST(stock_propio - %s, 0) WHERE cuenta_id = %s AND id_variante = %s",
            (cantidad, cuenta_id, id_variante)
        )

    if not descontar_en_meli:
        return True, None, None
    if _en_full(variante):
        return True, None, AVISO_FULL
    try:
        access_token = token_manager.asegurar_token_valido(cuenta_id)
    except token_manager.CuentaDesconectada:
        return True, None, _aviso_sin_descontar("tu cuenta está desconectada.")
    ok, motivo, nuevo = stock_meli.ajustar_en_meli(access_token, variante["id_meli"], variante["id_variante"], -cantidad)
    if not ok:
        return True, None, _aviso_sin_descontar(motivo)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE ventas SET stock_descontado_meli = true WHERE cuenta_id = %s AND id = %s", (cuenta_id, id_venta))
        cursor.execute("UPDATE productos_variantes SET stock_propio = %s WHERE cuenta_id = %s AND id_variante = %s", (nuevo, cuenta_id, id_variante))
    return True, None, None


def obtener_ventas_manuales_recientes(usuario_id, cuenta_id, limite=25):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT v.id, v.id_orden, v.titulo, v.id_variante, v.cantidad, v.precio_venta, v.fecha_venta, v.comprador_nombre, p.thumbnail
            FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.cuenta_id = %s AND v.origen = 'manual'
            ORDER BY v.id DESC LIMIT %s
        """, (cuenta_id, limite))
        filas = cursor.fetchall()

    return [{
        "id": f["id"], "titulo": f["titulo"], "thumbnail": f["thumbnail"], "id_variante": f["id_variante"], "cantidad": f["cantidad"],
        "total": float(f["precio_venta"]) * f["cantidad"],
        "precio_formateado": formatear_moneda(float(f["precio_venta"]) * f["cantidad"]),
        "fecha": f["fecha_venta"].strftime("%Y-%m-%d") if hasattr(f["fecha_venta"], "strftime") else f["fecha_venta"],
        "comprador_nombre": f["comprador_nombre"] or "—",
    } for f in filas]


def eliminar_venta_manual(usuario_id, cuenta_id, id_venta):
    """
    Borra una venta manual y le devuelve el stock a la variante — deshacer una carga por error. Si al registrarla se había descontado también en
    Mercado Libre, se devuelve ahí. Devuelve (se_borró, aviso_o_None).
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute(
            "SELECT id_variante, id_meli, cantidad, stock_descontado_meli FROM ventas WHERE cuenta_id = %s AND id = %s AND origen = 'manual'",
            (cuenta_id, id_venta)
        )
        fila = cursor.fetchone()
        if not fila:
            return False, None

        cursor.execute("DELETE FROM ventas WHERE cuenta_id = %s AND id = %s AND origen = 'manual'", (cuenta_id, id_venta))
        cursor.execute(
            "UPDATE productos_variantes SET stock_propio = stock_propio + %s WHERE cuenta_id = %s AND id_variante = %s",
            (fila["cantidad"], cuenta_id, fila["id_variante"])
        )

    if not fila["stock_descontado_meli"]:
        return True, None
    try:
        access_token = token_manager.asegurar_token_valido(cuenta_id)
    except token_manager.CuentaDesconectada:
        return True, "Se borró la venta, pero no pudimos devolver el stock en Mercado Libre (tu cuenta está desconectada). Sumalo vos ahí."
    ok, motivo, _ = stock_meli.ajustar_en_meli(access_token, fila["id_meli"], fila["id_variante"], fila["cantidad"])
    if not ok:
        return True, f"Se borró la venta, pero no pudimos devolver el stock en Mercado Libre ({motivo}) Sumalo vos ahí."
    return True, None

"""
Promociones — portado de Santi Mens. Cambios reales (no cosméticos):
- Postgres devuelve columnas DATE como objetos `date` de Python, no
  strings — las funciones que hacían datetime.strptime(fecha, ...)
  ahora aceptan ambos casos.
- El join de variantes pasa a usar productos_padre.id (igual que en el
  resto del port), no id_meli.
"""
import historial_precios
import meli_errores
import meli_http
from datetime import datetime, timedelta
from utils import hoy_argentina

APP_VERSION = "v2"


def _a_fecha(valor):
    """Normaliza una columna de fecha de Postgres (date o string) a date."""
    if hasattr(valor, "strftime"):
        return valor
    return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()


def registrar_inicio_promocion(cursor, cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_fin_planeada=None):
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    hace_7 = (hoy_argentina() - timedelta(days=7)).strftime("%Y-%m-%d")
    cursor.execute("SELECT COALESCE(SUM(cantidad),0) FROM ventas WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s", (id_meli, hace_7, hoy))
    unidades_previas = cursor.fetchone()[0] or 0
    promedio_diario_previo = round(unidades_previas / 7, 2)

    cursor.execute("""
        INSERT INTO historial_promociones (cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_inicio, fecha_fin_planeada, promedio_diario_previo, activo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
    """, (cuenta_id, id_meli, titulo, precio_original, precio_promo, hoy, fecha_fin_planeada, promedio_diario_previo))


def obtener_promociones_por_vencer(cursor, dias_aviso=2):
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    limite = (hoy_argentina() + timedelta(days=dias_aviso)).strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id_meli, titulo, fecha_fin_planeada FROM historial_promociones
        WHERE activo = true AND fecha_fin_planeada IS NOT NULL AND fecha_fin_planeada BETWEEN %s AND %s
    """, (hoy, limite))
    return [{"id_meli": r[0], "titulo": r[1], "fecha_fin_planeada": _a_fecha(r[2]).strftime("%Y-%m-%d")} for r in cursor.fetchall()]


def cerrar_promocion_activa(cursor, id_meli):
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    cursor.execute("UPDATE historial_promociones SET activo = false, fecha_fin = %s WHERE id_meli = %s AND activo = true", (hoy, id_meli))


def obtener_impacto_promociones(cursor):
    cursor.execute("""
        SELECT h.id, h.id_meli, h.titulo, h.precio_original, h.precio_promo, h.fecha_inicio, h.fecha_fin, h.promedio_diario_previo, h.activo, p.thumbnail
        FROM historial_promociones h
        LEFT JOIN productos_padre p ON p.id_meli = h.id_meli AND p.cuenta_id = h.cuenta_id
        ORDER BY h.fecha_inicio DESC LIMIT 30
    """)
    filas = cursor.fetchall()
    hoy = hoy_argentina()

    # Las unidades vendidas durante cada promoción salen de UNA consulta de ventas (por publicación y día) para las 30 promociones (antes, una consulta por promoción)
    ventanas = [(_a_fecha(f[5]), _a_fecha(f[6]) if f[6] else hoy) for f in filas]
    ventas = historial_precios.ventas_diarias(
        cursor, {f[1] for f in filas},
        min((d.strftime("%Y-%m-%d") for d, _ in ventanas), default=None), max((h.strftime("%Y-%m-%d") for _, h in ventanas), default=None)) if filas else {}

    resultados = []
    for (id_hist, id_meli, titulo, precio_orig, precio_promo, fecha_inicio, fecha_fin, promedio_previo, activo, thumbnail), (fecha_inicio_dt, fecha_hasta_calculo_dt) in zip(filas, ventanas):
        dias_transcurridos = max((fecha_hasta_calculo_dt - fecha_inicio_dt).days, 1)

        unidades_durante = historial_precios.unidades_en_ventana(ventas, id_meli, fecha_inicio_dt.strftime("%Y-%m-%d"), fecha_hasta_calculo_dt.strftime("%Y-%m-%d"))
        promedio_durante = round(unidades_durante / dias_transcurridos, 2)

        variacion_pct = None
        if promedio_previo and float(promedio_previo) > 0:
            variacion_pct = round(((promedio_durante - float(promedio_previo)) / float(promedio_previo)) * 100, 1)

        resultados.append({
            "id_meli": id_meli, "titulo": titulo, "thumbnail": thumbnail, "precio_original": precio_orig, "precio_promo": precio_promo,
            "fecha_inicio": fecha_inicio_dt.strftime("%Y-%m-%d"), "fecha_fin": _a_fecha(fecha_fin).strftime("%Y-%m-%d") if fecha_fin else None,
            "activo": bool(activo), "promedio_previo": float(promedio_previo or 0), "promedio_durante": promedio_durante,
            "variacion_pct": variacion_pct, "unidades_durante": unidades_durante,
        })
    return resultados


def sugerir_candidatos_promocion(cursor, umbral_dias_sin_rotar=20):
    hoy = hoy_argentina().strftime("%Y-%m-%d")
    hace_14 = (hoy_argentina() - timedelta(days=14)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.precio, p.precio_costo,
               SUM(COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0)) as stock_total, p.thumbnail
        FROM productos_padre p
        JOIN productos_variantes v ON v.id_padre = p.id
        WHERE p.estado = 'active'
        GROUP BY p.id_meli, p.titulo, p.precio, p.precio_costo, p.thumbnail
        HAVING SUM(COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0)) >= 4
    """)
    candidatos_potenciales = cursor.fetchall()

    cursor.execute("SELECT id_meli, COALESCE(SUM(cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s GROUP BY id_meli", (hace_14, hoy))
    ventas_recientes = dict(cursor.fetchall())

    cursor.execute("SELECT id_meli FROM historial_promociones WHERE activo = true")
    ya_en_promo = {r[0] for r in cursor.fetchall()}

    sugeridos = []
    for id_meli, titulo, precio, precio_costo, stock_total, thumbnail in candidatos_potenciales:
        if id_meli in ya_en_promo:
            continue
        unidades_14d = ventas_recientes.get(id_meli, 0)
        dias_para_agotar_a_este_ritmo = (stock_total / (unidades_14d / 14)) if unidades_14d > 0 else 999
        if dias_para_agotar_a_este_ritmo >= umbral_dias_sin_rotar:
            sugeridos.append({
                "id_meli": id_meli, "titulo": titulo, "thumbnail": thumbnail, "precio": float(precio or 0), "precio_costo": float(precio_costo or 0),
                "stock_total": stock_total, "unidades_14d": unidades_14d,
                "capital_inmovilizado": round(float(precio or 0) * stock_total, 2),
            })

    sugeridos.sort(key=lambda s: -s["capital_inmovilizado"])
    return sugeridos[:8]


_TIPOS_CAMPANIA_LEGIBLES = {
    "MARKETPLACE_CAMPAIGN": "Cofinanciada",
    "DEAL": "Tradicional",
    "PRICE_MATCHING": "Precios competitivos",
    "SMART": "Cofinanciada automática",
    "LIGHTNING": "Oferta relámpago",
    "SELLER_COUPON_CAMPAIGN": "Cupón de descuento",
    "PRE_NEGOTIATED": "Prenegociada",
}
_ESTADOS_CAMPANIA_LEGIBLES = {
    "started": ("En curso", "badge-success"),
    "active": ("En curso", "badge-success"),
    "candidate": ("Podés sumarte", "badge-info"),
    "pending": ("Pendiente de aprobación", "badge-warning"),
    "finished": ("Finalizada", "badge-neutral"),
    "rejected": ("Rechazada", "badge-neutral"),
}


def _fecha_campania_legible(iso_str):
    """MeLi devuelve fechas de campaña como ISO-8601 completo con hora y
    zona ("2026-09-06T03:50:00Z") — mostrar eso crudo en una tabla es
    ruido; acá solo interesa el día."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(iso_str)[:10]


def formatear_campanias_para_vista(campanias):
    """
    Traduce los campos crudos de la API de campañas de MeLi (tipos y
    estados en inglés/códigos internos, fechas ISO completas) a algo
    legible para la tabla — sin esto la pantalla de Promociones mostraba
    "started", "SELLER_COUPON_CAMPAIGN" y timestamps con hora tal cual
    los manda la API.
    """
    resultado = []
    for c in campanias:
        tipo_raw = c.get("type")
        estado_raw = c.get("status")
        estado_texto, estado_clase = _ESTADOS_CAMPANIA_LEGIBLES.get(estado_raw, (estado_raw, "badge-neutral"))
        benefits = c.get("benefits") or {}
        resultado.append({
            "nombre": c.get("name") or c.get("id"),
            "tipo_texto": _TIPOS_CAMPANIA_LEGIBLES.get(tipo_raw, tipo_raw),
            "estado_texto": estado_texto, "estado_clase": estado_clase,
            "vigencia_desde": _fecha_campania_legible(c.get("start_date")),
            "vigencia_hasta": _fecha_campania_legible(c.get("finish_date")),
            "meli_percent": benefits.get("meli_percent") if "meli_percent" in benefits else None,
            "seller_percent": benefits.get("seller_percent") if "meli_percent" in benefits else None,
        })
    return resultado


def obtener_promociones_usuario(access_token, user_id):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/seller-promotions/users/{user_id}", headers=headers, params={"app_version": APP_VERSION}, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("results", [])
        print(f"[Promociones] ⚠️ No se pudieron traer las campañas: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[Promociones] ❌ Error de conexión: {e}")
    return []


def crear_descuento_individual(access_token, item_id, deal_price, fecha_desde, fecha_hasta):
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {"deal_price": deal_price, "start_date": f"{fecha_desde}T00:00:00", "finish_date": f"{fecha_hasta}T23:59:59", "promotion_type": "PRICE_DISCOUNT"}
    try:
        resp = meli_http.post(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", headers=headers, params={"app_version": APP_VERSION}, json=body, timeout=10)
        if resp.status_code in (200, 201):
            return True, resp.json()
        return False, meli_errores.explicar_respuesta(resp)
    except Exception as e:
        print(f"[Promociones] ⚠️ Sin conexión al crear el descuento de {item_id}: {e}")
        return False, meli_errores.SIN_CONEXION


def eliminar_promocion_item(access_token, item_id, promotion_type):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.delete(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", headers=headers, params={"app_version": APP_VERSION, "promotion_type": promotion_type}, timeout=10)
        if resp.status_code == 200:
            return True, ""
        return False, meli_errores.explicar_respuesta(resp)
    except Exception as e:
        print(f"[Promociones] ⚠️ Sin conexión al eliminar el descuento de {item_id}: {e}")
        return False, meli_errores.SIN_CONEXION


def obtener_cupones(cursor, cuenta_id, dias=30):
    """
    Cupones que el vendedor financió en los últimos `dias` días (ventas.cupones: el cargo "coupon_fee" del pago). Es plata que MeLi
    descuenta de lo depositado y que ya está dentro de cargo_venta, o sea que Ganancia Real la resta. Los cupones que paga MeLi no
    le cuestan nada al vendedor y no se cuentan. Devuelve None si no hubo ninguno (la pantalla no muestra nada).
    """
    cursor.execute("""
        SELECT COALESCE(SUM(cupones), 0), COUNT(*) FILTER (WHERE COALESCE(cupones, 0) > 0), COUNT(*), COALESCE(SUM(precio_venta * cantidad), 0)
        FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta >= current_date - %s
    """, (cuenta_id, dias))
    total, con_cupon, ventas, facturado = cursor.fetchone()
    total, facturado = float(total), float(facturado)
    if total <= 0:
        return None
    cursor.execute("""
        SELECT v.id_meli, MAX(v.titulo), MAX(p.thumbnail), SUM(v.cupones), COUNT(*) FILTER (WHERE COALESCE(v.cupones, 0) > 0)
        FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
        WHERE v.cuenta_id = %s AND v.origen = 'meli' AND v.fecha_venta >= current_date - %s
        GROUP BY v.id_meli HAVING SUM(COALESCE(v.cupones, 0)) > 0 ORDER BY 4 DESC LIMIT 8
    """, (cuenta_id, dias))
    top = [{"id_meli": r[0], "titulo": r[1], "thumbnail": r[2], "total": float(r[3]), "ventas": int(r[4])} for r in cursor.fetchall()]
    return {"dias": dias, "total": round(total, 2), "ventas_con_cupon": int(con_cupon), "ventas": int(ventas),
            "pct_facturado": round(total / facturado * 100, 1) if facturado > 0 else None,
            "promedio": round(total / con_cupon, 2) if con_cupon else 0, "top": top}

"""
Promociones — portado de Santi Mens. Cambios reales (no cosméticos):
- Postgres devuelve columnas DATE como objetos `date` de Python, no
  strings — las funciones que hacían datetime.strptime(fecha, ...)
  ahora aceptan ambos casos.
- El join de variantes pasa a usar productos_padre.id (igual que en el
  resto del port), no id_meli.
"""
import meli_http
from datetime import datetime, timedelta

APP_VERSION = "v2"


def _a_fecha(valor):
    """Normaliza una columna de fecha de Postgres (date o string) a date."""
    if hasattr(valor, "strftime"):
        return valor
    return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()


def registrar_inicio_promocion(cursor, cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_fin_planeada=None):
    hoy = datetime.now().strftime("%Y-%m-%d")
    hace_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    cursor.execute("SELECT COALESCE(SUM(cantidad),0) FROM ventas WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s", (id_meli, hace_7, hoy))
    unidades_previas = cursor.fetchone()[0] or 0
    promedio_diario_previo = round(unidades_previas / 7, 2)

    cursor.execute("""
        INSERT INTO historial_promociones (cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_inicio, fecha_fin_planeada, promedio_diario_previo, activo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
    """, (cuenta_id, id_meli, titulo, precio_original, precio_promo, hoy, fecha_fin_planeada, promedio_diario_previo))


def obtener_promociones_por_vencer(cursor, dias_aviso=2):
    hoy = datetime.now().strftime("%Y-%m-%d")
    limite = (datetime.now() + timedelta(days=dias_aviso)).strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id_meli, titulo, fecha_fin_planeada FROM historial_promociones
        WHERE activo = true AND fecha_fin_planeada IS NOT NULL AND fecha_fin_planeada BETWEEN %s AND %s
    """, (hoy, limite))
    return [{"id_meli": r[0], "titulo": r[1], "fecha_fin_planeada": _a_fecha(r[2]).strftime("%Y-%m-%d")} for r in cursor.fetchall()]


def cerrar_promocion_activa(cursor, id_meli):
    hoy = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("UPDATE historial_promociones SET activo = false, fecha_fin = %s WHERE id_meli = %s AND activo = true", (hoy, id_meli))


def obtener_impacto_promociones(cursor):
    cursor.execute("""
        SELECT id, id_meli, titulo, precio_original, precio_promo, fecha_inicio, fecha_fin, promedio_diario_previo, activo
        FROM historial_promociones ORDER BY fecha_inicio DESC LIMIT 30
    """)
    filas = cursor.fetchall()
    hoy = datetime.now().date()

    resultados = []
    for id_hist, id_meli, titulo, precio_orig, precio_promo, fecha_inicio, fecha_fin, promedio_previo, activo in filas:
        fecha_inicio_dt = _a_fecha(fecha_inicio)
        fecha_hasta_calculo_dt = _a_fecha(fecha_fin) if fecha_fin else hoy
        dias_transcurridos = max((fecha_hasta_calculo_dt - fecha_inicio_dt).days, 1)

        cursor.execute("SELECT COALESCE(SUM(cantidad),0) FROM ventas WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s",
                        (id_meli, fecha_inicio_dt.strftime("%Y-%m-%d"), fecha_hasta_calculo_dt.strftime("%Y-%m-%d")))
        unidades_durante = cursor.fetchone()[0] or 0
        promedio_durante = round(unidades_durante / dias_transcurridos, 2)

        variacion_pct = None
        if promedio_previo and float(promedio_previo) > 0:
            variacion_pct = round(((promedio_durante - float(promedio_previo)) / float(promedio_previo)) * 100, 1)

        resultados.append({
            "id_meli": id_meli, "titulo": titulo, "precio_original": precio_orig, "precio_promo": precio_promo,
            "fecha_inicio": fecha_inicio_dt.strftime("%Y-%m-%d"), "fecha_fin": _a_fecha(fecha_fin).strftime("%Y-%m-%d") if fecha_fin else None,
            "activo": bool(activo), "promedio_previo": float(promedio_previo or 0), "promedio_durante": promedio_durante,
            "variacion_pct": variacion_pct, "unidades_durante": unidades_durante,
        })
    return resultados


def sugerir_candidatos_promocion(cursor, umbral_dias_sin_rotar=20):
    hoy = datetime.now().strftime("%Y-%m-%d")
    hace_14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.precio, p.precio_costo,
               SUM(COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0)) as stock_total
        FROM productos_padre p
        JOIN productos_variantes v ON v.id_padre = p.id
        WHERE p.estado = 'active'
        GROUP BY p.id_meli, p.titulo, p.precio, p.precio_costo
        HAVING SUM(COALESCE(v.stock_propio,0) + COALESCE(v.stock_full,0)) >= 4
    """)
    candidatos_potenciales = cursor.fetchall()

    cursor.execute("SELECT id_meli, COALESCE(SUM(cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s GROUP BY id_meli", (hace_14, hoy))
    ventas_recientes = dict(cursor.fetchall())

    cursor.execute("SELECT id_meli FROM historial_promociones WHERE activo = true")
    ya_en_promo = {r[0] for r in cursor.fetchall()}

    sugeridos = []
    for id_meli, titulo, precio, precio_costo, stock_total in candidatos_potenciales:
        if id_meli in ya_en_promo:
            continue
        unidades_14d = ventas_recientes.get(id_meli, 0)
        dias_para_agotar_a_este_ritmo = (stock_total / (unidades_14d / 14)) if unidades_14d > 0 else 999
        if dias_para_agotar_a_este_ritmo >= umbral_dias_sin_rotar:
            sugeridos.append({
                "id_meli": id_meli, "titulo": titulo, "precio": float(precio or 0), "precio_costo": float(precio_costo or 0),
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


def obtener_items_oferta_relampago(access_token, promotion_id):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/seller-promotions/promotions/{promotion_id}/items",
                             headers=headers, params={"app_version": APP_VERSION, "promotion_type": "LIGHTNING"}, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("results", [])
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
        return False, f"{resp.status_code} - {resp.text}"
    except Exception as e:
        return False, str(e)


def eliminar_promocion_item(access_token, item_id, promotion_type):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.delete(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", headers=headers, params={"app_version": APP_VERSION, "promotion_type": promotion_type}, timeout=10)
        return resp.status_code == 200, f"{resp.status_code}"
    except Exception as e:
        return False, str(e)


def participar_oferta_relampago(access_token, item_id, deal_price, stock):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.post(f"https://api.mercadolibre.com/seller-promotions/promotions/items/{item_id}",
                              headers=headers, params={"app_version": APP_VERSION}, json={"deal_price": deal_price, "stock_quantity": stock, "promotion_type": "LIGHTNING"}, timeout=10)
        if resp.status_code in (200, 201):
            return True, resp.json()
        return False, f"{resp.status_code} - {resp.text}"
    except Exception as e:
        return False, str(e)

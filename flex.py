"""
Costo de entrega de Flex.

En Flex el vendedor entrega con su propia logística y MeLi reporta costo_envio = 0: el costo real lo cobra esa logística
por zona. Las zonas las define Mercado Libre (ver flex_zonas.py), así que el usuario solo carga lo que le cobra su
logística: "umbrales", cada uno con un precio y las zonas que cubre. Las zonas que no mueve a ningún umbral caen en el
umbral "resto" (siempre existe). cuentas_meli.flex_umbrales guarda los umbrales y cuentas_meli.flex_info lo que se
sincronizó de MeLi (servicio, domicilio de salida y zonas de cobertura).

MeLi le reintegra al vendedor el 10% del envío, así que el costo que se descuenta de la ganancia es el precio del
umbral menos ese 10% (REINTEGRO_MELI). La pantalla lo explica.

ventas.costo_envio es "el envío total que te cuesta": lo que informa MeLi más ventas.costo_flex. Por eso Ganancia Real,
Dashboard, Facturación y el reporte fiscal lo incluyen sin tocar cada cálculo, y por eso toda asignación mueve
costo_flex y costo_envio juntos. ventas.flex_zona es el id del umbral aplicado (0 = sin costo, NULL = pendiente) y
ventas.flex_zona_meli la zona de MeLi donde se ubicó el envío ('*manual' si el usuario eligió el umbral a mano: las
asignaciones manuales y "sin costo" no se tocan al recalcular). Una venta ya valuada conserva su precio salvo que el
usuario pida recalcular.
"""
from datetime import datetime, timezone
import json
import meli_http
import flex_zonas as fz

REINTEGRO_MELI = 0.10
TOPE_PRECIO = 10_000_000
MAX_UMBRALES = 8
ZONA_SIN_COSTO = 0
MANUAL = "*manual"
SITE_ID = "MLA"

_DONDE_PENDIENTES = "flex_zona IS NULL"
_DONDE_VALUADAS = "flex_zona IS NOT NULL AND flex_zona <> 0 AND COALESCE(flex_zona_meli, '') <> '*manual'"


def neto(precio):
    """Lo que de verdad cuesta un envío: el precio de la logística menos el reintegro de MeLi."""
    return None if precio is None else round(float(precio) * (1 - REINTEGRO_MELI), 2)


# ── Configuración ──────────────────────────────────────────────────────────

def _umbral_resto():
    return {"id": 1, "nombre": None, "precio": None, "zonas": [], "resto": True}


def obtener_config(cursor, cuenta_id):
    """{"umbrales": [...], "info": {...}|None}. El umbral "resto" existe siempre y va primero."""
    cursor.execute("SELECT flex_umbrales, flex_info FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila = cursor.fetchone()
    umbrales = fila[0] if fila and isinstance(fila[0], list) else []
    info = fila[1] if fila and isinstance(fila[1], dict) else None
    if not any(u.get("resto") for u in umbrales):
        umbrales = [_umbral_resto()] + umbrales
    umbrales.sort(key=lambda u: (not u.get("resto"), u.get("id", 0)))
    return {"umbrales": umbrales, "info": info}


def etiqueta(umbral, nombres_zona):
    """Nombre para mostrar: el que puso el usuario, o la primera zona (+N), o "Resto de las zonas"."""
    if umbral.get("nombre"):
        return umbral["nombre"]
    if umbral.get("resto"):
        return "Resto de las zonas"
    zonas = sorted(nombres_zona.get(z, fz.nombre_zona(z)) for z in umbral.get("zonas", []))
    if not zonas:
        return "Umbral sin zonas"
    return zonas[0] + (f" +{len(zonas) - 1}" if len(zonas) > 1 else "")


def _nombres_de_zona(info):
    return {z["id"]: z["nombre"] for z in (info or {}).get("zonas", [])}


def umbrales_para_vista(config):
    """Umbrales con etiqueta y costo neto ya calculados, para las pantallas."""
    nombres = _nombres_de_zona(config["info"])
    return [{**u, "etiqueta": etiqueta(u, nombres), "neto": neto(u.get("precio"))} for u in config["umbrales"]]


def guardar_umbrales(cursor, cuenta_id, umbrales):
    """Valida todo antes de escribir. Devuelve (ok, error). Los ids nuevos (null) se asignan acá."""
    if not isinstance(umbrales, list) or len(umbrales) > MAX_UMBRALES:
        return False, f"Se pueden tener hasta {MAX_UMBRALES} umbrales."
    info = obtener_config(cursor, cuenta_id)["info"]
    conocidas = {z["id"] for z in (info or {}).get("zonas", [])}
    limpios, ids_usados, zonas_usadas = [], set(), set()
    for u in umbrales:
        if not isinstance(u, dict):
            return False, "Umbral inválido."
        precio = u.get("precio")
        if precio is None or (isinstance(precio, str) and not precio.strip()):
            precio = None
        else:
            try:
                precio = round(float(str(precio).replace(",", ".")), 2)
            except ValueError:
                return False, "Un precio no es un número válido."
            if not (0 <= precio < TOPE_PRECIO):
                return False, "Los precios tienen que estar entre $0 y $10.000.000."
        nombre = str(u.get("nombre") or "").strip()[:40] or None
        zonas = [] if u.get("resto") else [z for z in (u.get("zonas") or []) if isinstance(z, str)]
        for z in zonas:
            if conocidas and z not in conocidas:
                return False, f"La zona {fz.nombre_zona(z)} no está en tu cobertura de Mercado Libre. Sincronizá las zonas."
            if z in zonas_usadas:
                return False, f"La zona {fz.nombre_zona(z)} está en dos umbrales."
            zonas_usadas.add(z)
        uid = u.get("id")
        uid = int(uid) if isinstance(uid, (int, float)) and 1 <= int(uid) <= 99 and int(uid) not in ids_usados else None
        if uid is not None:
            ids_usados.add(uid)
        limpios.append({"id": uid, "nombre": nombre, "precio": precio, "zonas": zonas, "resto": bool(u.get("resto"))})
    if sum(1 for u in limpios if u["resto"]) != 1:
        return False, "Tiene que haber un umbral para el resto de las zonas."
    siguiente = max(ids_usados | {1}) + 1
    for u in limpios:
        if u["id"] is None:
            u["id"] = siguiente
            siguiente += 1
    cursor.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(limpios), cuenta_id))
    return True, None


def sincronizar_con_meli(cursor, cuenta_id, access_token, seller_id):
    """
    Trae de MeLi el servicio Flex del vendedor, su domicilio de salida y las zonas de cobertura, y las guarda.
    Las zonas que MeLi ya no cubre se sacan de los umbrales. Devuelve (ok, error).
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/flex/sites/{SITE_ID}/users/{seller_id}/subscriptions/v1", headers=headers, timeout=10)
        if resp.status_code != 200:
            return False, "Mercado Libre no informó una suscripción Flex para tu cuenta."
        flex = next((s for s in resp.json() if s.get("mode") == "FLEX"), None)
        if not flex or flex.get("status") != "in":
            return False, "Tu cuenta no tiene Mercado Envíos Flex activo."
        service_id = flex["service_id"]
        resp_zonas = meli_http.get(
            f"https://api.mercadolibre.com/flex/sites/{SITE_ID}/users/{seller_id}/services/{service_id}/configurations/coverage/zones/v1",
            headers=headers, timeout=10)
        if resp_zonas.status_code != 200:
            return False, "No pude traer tus zonas de cobertura de Mercado Libre. Probá de nuevo en un rato."
        zonas = sorted(({"id": z["id"], "nombre": fz.nombre_zona(z["id"])} for z in resp_zonas.json().get("zones", [])),
                       key=lambda z: z["nombre"])
    except Exception as e:
        print(f"[Flex] ⚠️ Error sincronizando zonas con MeLi: {e}")
        return False, "No pude conectar con Mercado Libre. Probá de nuevo."
    origen = flex.get("origin") or {}
    info = {"service_id": service_id, "zonas": zonas, "sincronizado_en": datetime.now(timezone.utc).isoformat(),
            "origen": {"direccion": origen.get("address_line"), "ciudad": (origen.get("city") or {}).get("name"), "cp": origen.get("zip_code")}}
    cursor.execute("UPDATE cuentas_meli SET flex_info = %s::jsonb WHERE id = %s", (json.dumps(info), cuenta_id))
    ids = {z["id"] for z in zonas}
    umbrales = obtener_config(cursor, cuenta_id)["umbrales"]
    for u in umbrales:
        u["zonas"] = [z for z in u["zonas"] if z in ids]
    cursor.execute("UPDATE cuentas_meli SET flex_umbrales = %s::jsonb WHERE id = %s", (json.dumps(umbrales), cuenta_id))
    return True, None


def sincronizacion_vieja(info, dias=7):
    if not info or not info.get("sincronizado_en"):
        return True
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(info["sincronizado_en"])).days >= dias
    except ValueError:
        return True


# ── Asignación ─────────────────────────────────────────────────────────────

def _aplicar(cursor, cuenta_id, ids_orden, umbral_id, precio_neto, zona_meli):
    """
    Pone el umbral y su costo a las ventas Flex de esas órdenes, en una sola sentencia para cualquier cantidad. Si la
    orden tiene varios ítems el costo se reparte en proporción a lo facturado por cada uno (igual que el envío de
    MeLi). costo_envio se corrige por la diferencia, así nunca se suma dos veces.
    """
    if not ids_orden:
        return
    cursor.execute("""
        UPDATE ventas v SET flex_zona = %(umbral)s, flex_zona_meli = %(zona_meli)s,
            costo_flex = COALESCE(ROUND(%(precio)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0),
            costo_envio = v.costo_envio - v.costo_flex + COALESCE(ROUND(%(precio)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0)
        FROM (SELECT id_orden, SUM(precio_venta * cantidad) AS fact FROM ventas
              WHERE cuenta_id = %(cuenta)s AND id_orden = ANY(%(ids)s) GROUP BY id_orden) t
        WHERE v.cuenta_id = %(cuenta)s AND v.id_orden = t.id_orden AND v.origen = 'meli' AND v.tipo_logistica = 'self_service'
    """, {"umbral": umbral_id, "zona_meli": zona_meli, "precio": precio_neto or 0, "cuenta": cuenta_id, "ids": list(ids_orden)})


def _ordenes(cursor, cuenta_id, donde):
    # `donde` son las constantes de arriba, nunca texto del usuario
    cursor.execute(f"""
        SELECT id_orden, MAX(provincia), MAX(localidad), MAX(destino_lat), MAX(destino_lon)
        FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND {donde}
        GROUP BY id_orden
    """, (cuenta_id,))
    return [{"id_orden": r[0], "provincia": r[1], "localidad": r[2],
             "lat": float(r[3]) if r[3] is not None else None, "lon": float(r[4]) if r[4] is not None else None} for r in cursor.fetchall()]


def umbral_de_familia(umbrales, familia):
    """Umbral que corresponde a una familia de zona: el que la tiene entre sus zonas, y si no, el resto."""
    for u in umbrales:
        if not u.get("resto") and familia and any(fz.familia_de_zona(z) == familia for z in u["zonas"]):
            return u
    return next(u for u in umbrales if u.get("resto"))


def _plan(cursor, cuenta_id, donde):
    """({(umbral_id, familia): [ordenes]}, umbrales, sin_precio) — qué umbral le toca a cada orden, según las zonas de MeLi."""
    umbrales = obtener_config(cursor, cuenta_id)["umbrales"]
    por_grupo, sin_precio = {}, 0
    for o in _ordenes(cursor, cuenta_id, donde):
        familia = fz.familia_de_destino(o["provincia"], o["localidad"], o["lat"], o["lon"])
        u = umbral_de_familia(umbrales, familia)
        if u.get("precio") is None:
            sin_precio += 1
        else:
            por_grupo.setdefault((u["id"], familia), []).append(o["id_orden"])
    return por_grupo, umbrales, sin_precio


def vista_previa(cursor, cuenta_id, incluir_valuadas=False):
    """Qué pasaría al aplicar, sin escribir nada: envíos y costo por umbral."""
    condiciones = [_DONDE_PENDIENTES] + ([_DONDE_VALUADAS] if incluir_valuadas else [])
    conteo, sin_precio, umbrales = {}, 0, None
    for donde in condiciones:
        por_grupo, umbrales, sp = _plan(cursor, cuenta_id, donde)
        sin_precio += sp
        for (uid, _fam), ordenes in por_grupo.items():
            conteo[uid] = conteo.get(uid, 0) + len(ordenes)
    config = obtener_config(cursor, cuenta_id)
    vista = umbrales_para_vista(config)
    filas = [{"id": u["id"], "etiqueta": u["etiqueta"], "ordenes": conteo[u["id"]], "costo": round(conteo[u["id"]] * (u["neto"] or 0), 2)}
             for u in vista if conteo.get(u["id"])]
    return {"umbrales": filas, "ordenes": sum(f["ordenes"] for f in filas), "costo_total": round(sum(f["costo"] for f in filas), 2), "sin_precio": sin_precio}


def aplicar_automatico(cursor, cuenta_id, incluir_valuadas=False):
    """
    Para el sync y cuando el usuario confirma: a cada orden Flex sin umbral se le aplica el que le corresponde según su
    zona (si ese umbral tiene precio). Con incluir_valuadas también se recalculan las ya valuadas con precios viejos
    (salvo las elegidas a mano y las "sin costo"). Devuelve cuántas órdenes se resolvieron.
    """
    total = 0
    for donde in [_DONDE_PENDIENTES] + ([_DONDE_VALUADAS] if incluir_valuadas else []):
        por_grupo, umbrales, _ = _plan(cursor, cuenta_id, donde)
        precios = {u["id"]: u["precio"] for u in umbrales}
        for (uid, familia), ordenes in por_grupo.items():
            _aplicar(cursor, cuenta_id, ordenes, uid, neto(precios[uid]), familia or "")
            total += len(ordenes)
    return total


def asignar_manual(cursor, cuenta_id, id_orden, umbral_id):
    """Elige a mano el umbral de UNA orden Flex (0 = sin costo). Queda marcada como manual. Devuelve (ok, error)."""
    cursor.execute("SELECT tipo_logistica FROM ventas WHERE cuenta_id = %s AND id_orden = %s AND origen = 'meli'", (cuenta_id, str(id_orden)))
    tipos = [r[0] for r in cursor.fetchall()]
    if not tipos:
        return False, "No encontré esa venta."
    if any(t != "self_service" for t in tipos):
        return False, "Esa venta no es de Flex."
    if umbral_id == ZONA_SIN_COSTO:
        precio_neto = 0.0
    else:
        umbral = next((u for u in obtener_config(cursor, cuenta_id)["umbrales"] if u["id"] == umbral_id), None)
        if not umbral:
            return False, "Ese umbral no existe."
        if umbral.get("precio") is None:
            return False, "Cargá primero el precio de ese umbral en Costos."
        precio_neto = neto(umbral["precio"])
    _aplicar(cursor, cuenta_id, [str(id_orden)], umbral_id, precio_neto, MANUAL)
    return True, None


def contar_pendientes(cursor, cuenta_id):
    cursor.execute("SELECT COUNT(DISTINCT id_orden) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND flex_zona IS NULL", (cuenta_id,))
    return int(cursor.fetchone()[0] or 0)


def resumen_periodo(cursor, cuenta_id, desde, hasta):
    """Para Ganancia Real: órdenes Flex del período, cuántas siguen sin costo de entrega y cuánto suma ya el costo Flex."""
    cursor.execute("""
        SELECT COUNT(DISTINCT id_orden),
               COUNT(DISTINCT id_orden) FILTER (WHERE flex_zona IS NULL),
               COALESCE(SUM(costo_flex), 0)
        FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND fecha_venta BETWEEN %s AND %s
    """, (cuenta_id, desde, hasta))
    ordenes, sin_zona, costo = cursor.fetchone()
    return {"ordenes": int(ordenes or 0), "sin_zona": int(sin_zona or 0), "costo": float(costo or 0)}

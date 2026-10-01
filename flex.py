"""
Costo de entrega de Flex por zona.

En Flex el vendedor entrega con su propia logística y esa logística le cobra
según la distancia: 3 zonas con precio distinto. Mercado Libre no conoce ese
costo (las ventas Flex vienen con costo_envio = 0), así que lo carga el usuario:
3 precios por cuenta (cuentas_meli.flex_tarifa_zona1..3) y la zona de cada venta
(ventas.flex_zona: 1 a 3, o 0 = "sin costo", por ejemplo si entrega el mismo).

ventas.costo_envio es "el envío total que te cuesta": lo que informa MeLi más
ventas.costo_flex. Por eso Ganancia Real, Dashboard, Facturación y el reporte
fiscal lo incluyen sin tocar cada cálculo, y por eso toda asignación de zona mueve
costo_flex y costo_envio juntos. Una vez asignada, la venta queda valuada al
precio de ese momento: cambiar las tarifas no reescribe el pasado salvo que el
usuario lo pida (recalcular_zonas_asignadas).

Elegir la zona de cada envío a mano no escala (una cuenta puede tener 100+ envíos
Flex por mes), así que la zona que el usuario elige para una localidad (o un
código postal puntual, que tiene prioridad) queda recordada en
cuentas_meli.flex_zonas_memoria y se aplica sola a los envíos nuevos.

Mejor todavía: la logística cobra por distancia desde el domicilio de salida, y
MeLi trae las coordenadas exactas del destino de cada envío. Con el código postal
de salida y hasta cuántos km llega cada zona (regla de distancia, opcional) la
zona se calcula sola. Prioridad al aplicar: lo que el usuario eligió a mano para
un código postal o localidad > la regla de distancia.
"""
import json
import math
import re
import unicodedata
import meli_http

ZONAS = (1, 2, 3)
ZONA_SIN_COSTO = 0
TOPE_TARIFA = 10_000_000


# ── Tarifas ────────────────────────────────────────────────────────────────

def obtener_tarifas(cursor, cuenta_id):
    """{1: precio|None, 2: ..., 3: ...} — None es "todavía no cargó ese precio"."""
    cursor.execute("SELECT flex_tarifa_zona1, flex_tarifa_zona2, flex_tarifa_zona3 FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila = cursor.fetchone()
    return {z: (float(fila[z - 1]) if fila and fila[z - 1] is not None else None) for z in ZONAS}


def guardar_tarifas(cursor, cuenta_id, tarifas):
    """
    `tarifas`: {1: valor, 2: valor, 3: valor}; un valor vacío/None deja esa zona sin precio.
    Se valida todo antes de escribir. Devuelve (ok, error).
    """
    limpias = {}
    for z in ZONAS:
        crudo = tarifas.get(z)
        if crudo is None or (isinstance(crudo, str) and not crudo.strip()):
            limpias[z] = None
            continue
        try:
            valor = float(str(crudo).replace(",", "."))
        except ValueError:
            return False, f"El precio de la Zona {z} no es un número válido."
        if not (0 <= valor < TOPE_TARIFA):
            return False, f"El precio de la Zona {z} tiene que estar entre $0 y $10.000.000."
        limpias[z] = round(valor, 2)
    cursor.execute(
        "UPDATE cuentas_meli SET flex_tarifa_zona1 = %s, flex_tarifa_zona2 = %s, flex_tarifa_zona3 = %s WHERE id = %s",
        (limpias[1], limpias[2], limpias[3], cuenta_id),
    )
    return True, None


# ── Memoria de zonas por lugar ─────────────────────────────────────────────

def _normalizar(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def clave_cp(codigo_postal):
    """"1405" y "C1405ABC" → "cp:1405"."""
    digitos = re.sub(r"\D", "", codigo_postal or "")
    return f"cp:{digitos[:4]}" if len(digitos) >= 4 else None


def clave_localidad(provincia, localidad):
    loc = _normalizar(localidad)
    return f"loc:{_normalizar(provincia)}|{loc}" if loc else None


def obtener_memoria(cursor, cuenta_id):
    cursor.execute("SELECT flex_zonas_memoria FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila = cursor.fetchone()
    memoria = fila[0] if fila and fila[0] else {}
    return memoria if isinstance(memoria, dict) else {}


def _recordar(cursor, cuenta_id, clave, zona):
    if clave:
        cursor.execute("UPDATE cuentas_meli SET flex_zonas_memoria = flex_zonas_memoria || %s::jsonb WHERE id = %s",
                       (json.dumps({clave: zona}), cuenta_id))


def _zona_recordada(memoria, codigo_postal, provincia, localidad):
    """El código postal tiene prioridad sobre la localidad (es más preciso)."""
    for clave in (clave_cp(codigo_postal), clave_localidad(provincia, localidad)):
        if clave and clave in memoria:
            return memoria[clave]
    return None


# ── Regla de distancia ─────────────────────────────────────────────────────

def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia en línea recta entre dos puntos (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def zona_por_distancia(km, km_zona1, km_zona2):
    return 1 if km <= km_zona1 else (2 if km <= km_zona2 else 3)


def obtener_regla_distancia(cursor, cuenta_id):
    """{origen_cp, origen_lat, origen_lon, km_zona1, km_zona2}, o None si no está configurada completa."""
    cursor.execute("SELECT flex_origen_cp, flex_origen_lat, flex_origen_lon, flex_km_zona1, flex_km_zona2 FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila = cursor.fetchone()
    if not fila or any(x is None for x in fila):
        return None
    return {"origen_cp": fila[0], "origen_lat": float(fila[1]), "origen_lon": float(fila[2]), "km_zona1": float(fila[3]), "km_zona2": float(fila[4])}


def _coordenadas_de_cp(access_token, codigo_postal):
    """(lat, lon) del centro de un código postal según MeLi, o None."""
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/countries/AR/zip_codes/{codigo_postal}",
                             headers={"Authorization": f"Bearer {access_token}"}, timeout=8)
        if resp.status_code != 200:
            return None
        geo = resp.json().get("geo_information") or {}
        return float(geo["latitude"]), float(geo["longitude"])
    except Exception:
        return None


def guardar_regla_distancia(cursor, cuenta_id, access_token, origen_cp, km_zona1, km_zona2):
    """
    Guarda desde qué código postal sale el vendedor y hasta cuántos km llega la zona 1 y la 2 (la 3 es más lejos).
    Los tres vacíos apagan la regla. Devuelve (ok, error).
    """
    def vacio(v):
        return v is None or str(v).strip() == ""
    if vacio(origen_cp) and vacio(km_zona1) and vacio(km_zona2):
        cursor.execute("UPDATE cuentas_meli SET flex_origen_cp = NULL, flex_origen_lat = NULL, flex_origen_lon = NULL, "
                       "flex_km_zona1 = NULL, flex_km_zona2 = NULL WHERE id = %s", (cuenta_id,))
        return True, None
    if vacio(origen_cp) or vacio(km_zona1) or vacio(km_zona2):
        return False, "Para calcular la zona por distancia completá el código postal de salida y los km de la Zona 1 y la Zona 2."
    digitos = re.sub(r"\D", "", str(origen_cp))
    if len(digitos) < 4:
        return False, "El código postal de salida tiene que tener 4 números."
    try:
        km1, km2 = float(str(km_zona1).replace(",", ".")), float(str(km_zona2).replace(",", "."))
    except ValueError:
        return False, "Los km tienen que ser números."
    if not (0 < km1 < km2 < 1000):
        return False, "Los km de la Zona 2 tienen que ser mayores que los de la Zona 1."
    coordenadas = _coordenadas_de_cp(access_token, digitos[:4])
    if not coordenadas:
        return False, f"No encontré el código postal {digitos[:4]} en Mercado Libre. Revisalo."
    cursor.execute("UPDATE cuentas_meli SET flex_origen_cp = %s, flex_origen_lat = %s, flex_origen_lon = %s, flex_km_zona1 = %s, flex_km_zona2 = %s WHERE id = %s",
                   (digitos[:4], round(coordenadas[0], 6), round(coordenadas[1], 6), km1, km2, cuenta_id))
    return True, None


# ── Asignación de zona ─────────────────────────────────────────────────────

def _aplicar_zona(cursor, cuenta_id, ids_orden, zona, tarifa):
    """
    Pone `zona` y su costo a las ventas Flex de esas órdenes. Una sola sentencia para cualquier cantidad de órdenes.
    Si la orden tiene varios ítems, el precio de la zona se reparte en proporción a lo facturado por cada uno (igual
    que el envío de MeLi). costo_envio se corrige por la diferencia, así nunca se suma dos veces.
    """
    if not ids_orden:
        return
    cursor.execute("""
        UPDATE ventas v SET flex_zona = %(zona)s,
            costo_flex = COALESCE(ROUND(%(tarifa)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0),
            costo_envio = v.costo_envio - v.costo_flex + COALESCE(ROUND(%(tarifa)s::numeric * (v.precio_venta * v.cantidad) / NULLIF(t.fact, 0), 2), 0)
        FROM (SELECT id_orden, SUM(precio_venta * cantidad) AS fact FROM ventas
              WHERE cuenta_id = %(cuenta)s AND id_orden = ANY(%(ids)s) GROUP BY id_orden) t
        WHERE v.cuenta_id = %(cuenta)s AND v.id_orden = t.id_orden AND v.origen = 'meli' AND v.tipo_logistica = 'self_service'
    """, {"zona": zona, "tarifa": tarifa or 0, "cuenta": cuenta_id, "ids": list(ids_orden)})


def _tarifa_de(cursor, cuenta_id, zona):
    """(tarifa, error): la zona 0 (sin costo) vale 0; 1 a 3 necesitan su precio cargado."""
    if zona == ZONA_SIN_COSTO:
        return 0.0, None
    tarifa = obtener_tarifas(cursor, cuenta_id)[zona]
    return tarifa, (None if tarifa is not None else f"Cargá primero el precio de la Zona {zona}.")


def asignar_zona(cursor, cuenta_id, id_orden, zona):
    """
    Pone (o saca, con zona=None) la zona de entrega de UNA orden Flex y mueve su costo.
    zona: 1 a 3, 0 = sin costo, None = volver a "sin zona". Devuelve (ok, error).
    """
    if zona is not None and zona not in (ZONA_SIN_COSTO,) + ZONAS:
        return False, "Zona inválida."
    cursor.execute("SELECT tipo_logistica FROM ventas WHERE cuenta_id = %s AND id_orden = %s AND origen = 'meli'", (cuenta_id, str(id_orden)))
    tipos = [r[0] for r in cursor.fetchall()]
    if not tipos:
        return False, "No encontré esa venta."
    if any(tipo != "self_service" for tipo in tipos):
        return False, "Esa venta no es de Flex."

    tarifa = 0.0
    if zona is not None:
        tarifa, error = _tarifa_de(cursor, cuenta_id, zona)
        if error:
            return False, error
    if zona is None:
        cursor.execute("UPDATE ventas SET flex_zona = NULL, costo_envio = costo_envio - costo_flex, costo_flex = 0 "
                       "WHERE cuenta_id = %s AND id_orden = %s AND origen = 'meli'", (cuenta_id, str(id_orden)))
    else:
        _aplicar_zona(cursor, cuenta_id, [str(id_orden)], zona, tarifa)
    return True, None


def _ordenes_pendientes(cursor, cuenta_id, desde=None):
    """Órdenes Flex sin zona: [{id_orden, provincia, localidad, codigo_postal, fecha, total}]."""
    cursor.execute("""
        SELECT id_orden, MAX(provincia), MAX(localidad), MAX(codigo_postal), MAX(fecha_venta), SUM(precio_venta * cantidad), MAX(titulo),
               MAX(destino_lat), MAX(destino_lon)
        FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND flex_zona IS NULL
          AND (%s::date IS NULL OR fecha_venta >= %s::date)
        GROUP BY id_orden
    """, (cuenta_id, desde, desde))
    return [{"id_orden": r[0], "provincia": r[1], "localidad": r[2], "codigo_postal": r[3], "fecha": r[4],
             "total": float(r[5] or 0), "titulo": r[6],
             "lat": float(r[7]) if r[7] is not None else None, "lon": float(r[8]) if r[8] is not None else None} for r in cursor.fetchall()]


def asignar_zona_recordando(cursor, cuenta_id, id_orden, zona):
    """
    Zona de una orden elegida a mano: además de valuarla, recuerda la zona para su código postal (o su localidad,
    si MeLi no informó código postal) y la aplica a las otras órdenes Flex sin zona de ese mismo lugar.
    Devuelve (ok, error, otras_ordenes_aplicadas).
    """
    ok, error = asignar_zona(cursor, cuenta_id, id_orden, zona)
    if not ok:
        return False, error, 0
    if zona is None:
        return True, None, 0
    cursor.execute("SELECT MAX(provincia), MAX(localidad), MAX(codigo_postal) FROM ventas WHERE cuenta_id = %s AND id_orden = %s", (cuenta_id, str(id_orden)))
    provincia, localidad, codigo_postal = cursor.fetchone()
    clave = clave_cp(codigo_postal) or clave_localidad(provincia, localidad)
    if not clave:
        return True, None, 0
    _recordar(cursor, cuenta_id, clave, zona)
    tarifa, _ = _tarifa_de(cursor, cuenta_id, zona)
    mismas = [o["id_orden"] for o in _ordenes_pendientes(cursor, cuenta_id)
              if (clave_cp(o["codigo_postal"]) or clave_localidad(o["provincia"], o["localidad"])) == clave]
    _aplicar_zona(cursor, cuenta_id, mismas, zona, tarifa)
    return True, None, len(mismas)


def asignar_zona_a_localidad(cursor, cuenta_id, provincia, localidad, zona):
    """
    Zona para TODOS los envíos Flex sin zona de una localidad, y queda recordada para los que lleguen después.
    Devuelve (ok, error, cantidad_de_ordenes).
    """
    if zona not in (ZONA_SIN_COSTO,) + ZONAS:
        return False, "Zona inválida.", 0
    clave = clave_localidad(provincia, localidad)
    if not clave:
        return False, "Falta la localidad.", 0
    tarifa, error = _tarifa_de(cursor, cuenta_id, zona)
    if error:
        return False, error, 0
    ordenes = [o["id_orden"] for o in _ordenes_pendientes(cursor, cuenta_id) if clave_localidad(o["provincia"], o["localidad"]) == clave]
    _aplicar_zona(cursor, cuenta_id, ordenes, zona, tarifa)
    _recordar(cursor, cuenta_id, clave, zona)
    return True, None, len(ordenes)


def _zona_automatica(orden, memoria, regla):
    """Zona que le corresponde a una orden sin zona, o None si no hay forma de saberlo: la memoria de lo que el usuario
    eligió para ese lugar, y si no, la regla de distancia."""
    zona = _zona_recordada(memoria, orden["codigo_postal"], orden["provincia"], orden["localidad"])
    if zona is not None:
        return zona
    if regla and orden["lat"] is not None and orden["lon"] is not None:
        return zona_por_distancia(distancia_km(regla["origen_lat"], regla["origen_lon"], orden["lat"], orden["lon"]), regla["km_zona1"], regla["km_zona2"])
    return None


def _resolver_pendientes(cursor, cuenta_id):
    """({zona: [ordenes]}, sin_resolver, sin_precio, tarifas) para las órdenes Flex sin zona, según memoria y regla de distancia."""
    memoria = obtener_memoria(cursor, cuenta_id)
    regla = obtener_regla_distancia(cursor, cuenta_id)
    tarifas = obtener_tarifas(cursor, cuenta_id)
    por_zona, sin_resolver, sin_precio = {}, [], []
    for o in _ordenes_pendientes(cursor, cuenta_id):
        zona = _zona_automatica(o, memoria, regla)
        if zona is None:
            sin_resolver.append(o)
        elif zona != ZONA_SIN_COSTO and tarifas.get(zona) is None:
            sin_precio.append(o)
        else:
            por_zona.setdefault(zona, []).append(o)
    return por_zona, sin_resolver, sin_precio, tarifas


def aplicar_zonas_automaticas(cursor, cuenta_id):
    """
    Para el sync, al guardar precios y cuando el usuario confirma la regla: a cada orden Flex sin zona cuyo lugar ya tiene
    zona recordada, o que entra en la regla de distancia (y cuyo precio está cargado), se le aplica. Devuelve cuántas se resolvieron.
    """
    por_zona, _, _, tarifas = _resolver_pendientes(cursor, cuenta_id)
    for zona, ordenes in por_zona.items():
        _aplicar_zona(cursor, cuenta_id, [o["id_orden"] for o in ordenes], zona, 0.0 if zona == ZONA_SIN_COSTO else tarifas[zona])
    return sum(len(o) for o in por_zona.values())


def vista_previa_automatica(cursor, cuenta_id):
    """Qué pasaría al aplicar las zonas automáticas, sin escribir nada: envíos y costo por zona."""
    por_zona, sin_resolver, sin_precio, tarifas = _resolver_pendientes(cursor, cuenta_id)
    zonas = []
    for zona in (1, 2, 3, ZONA_SIN_COSTO):
        n = len(por_zona.get(zona, []))
        if n:
            zonas.append({"zona": zona, "ordenes": n, "costo": round(n * (tarifas.get(zona) or 0.0), 2)})
    return {"zonas": zonas, "ordenes": sum(z["ordenes"] for z in zonas), "costo_total": round(sum(z["costo"] for z in zonas), 2),
            "sin_resolver": len(sin_resolver), "sin_precio": len(sin_precio)}


def recalcular_zonas_asignadas(cursor, cuenta_id):
    """Reaplica las tarifas ACTUALES a todas las órdenes que ya tienen zona. Devuelve cuántas órdenes se recalcularon."""
    tarifas = obtener_tarifas(cursor, cuenta_id)
    cursor.execute("SELECT DISTINCT id_orden, flex_zona FROM ventas WHERE cuenta_id = %s AND flex_zona IS NOT NULL", (cuenta_id,))
    por_zona = {}
    for id_orden, zona in cursor.fetchall():
        por_zona.setdefault(zona, []).append(id_orden)
    recalculadas = 0
    for zona, ordenes in por_zona.items():
        if zona != ZONA_SIN_COSTO and tarifas.get(zona) is None:
            continue   # esa zona ya no tiene precio: se deja como estaba en vez de inventar uno
        _aplicar_zona(cursor, cuenta_id, ordenes, zona, 0.0 if zona == ZONA_SIN_COSTO else tarifas[zona])
        recalculadas += len(ordenes)
    return recalculadas


# ── Para las pantallas ─────────────────────────────────────────────────────

def pendientes_de_zona(cursor, cuenta_id, desde, limite_sin_ubicacion=30):
    """
    Envíos Flex sin zona desde `desde` (AAAA-MM-DD), listos para mostrar:
      grupos: por localidad, del lugar con más envíos al que menos — una zona para todos los de ahí
      sin_ubicacion: los que MeLi no informó de dónde son (hay que elegirles la zona uno por uno)
    """
    grupos, sin_ubicacion = {}, []
    for o in sorted(_ordenes_pendientes(cursor, cuenta_id, desde), key=lambda x: (x["fecha"] or 0), reverse=True):
        clave = clave_localidad(o["provincia"], o["localidad"])
        if not clave:
            sin_ubicacion.append({"id_orden": o["id_orden"], "titulo": o["titulo"], "total": o["total"],
                                  "fecha": o["fecha"].strftime("%d/%m") if hasattr(o["fecha"], "strftime") else str(o["fecha"])})
            continue
        g = grupos.setdefault(clave, {"localidad": o["localidad"], "provincia": o["provincia"], "ordenes": 0, "total": 0.0, "codigos_postales": set()})
        g["ordenes"] += 1
        g["total"] += o["total"]
        if o["codigo_postal"]:
            g["codigos_postales"].add(o["codigo_postal"])
    lista = sorted(grupos.values(), key=lambda g: (-g["ordenes"], g["localidad"] or ""))
    for g in lista:
        g["codigos_postales"] = sorted(g["codigos_postales"])
    return {"grupos": lista, "sin_ubicacion": sin_ubicacion[:limite_sin_ubicacion], "total_sin_ubicacion": len(sin_ubicacion),
            "total_ordenes": sum(g["ordenes"] for g in lista) + len(sin_ubicacion)}


def resumen_periodo(cursor, cuenta_id, desde, hasta):
    """Para Ganancia Real: órdenes Flex del período, cuántas siguen sin zona y cuánto suma ya el costo Flex."""
    cursor.execute("""
        SELECT COUNT(DISTINCT id_orden),
               COUNT(DISTINCT id_orden) FILTER (WHERE flex_zona IS NULL),
               COALESCE(SUM(costo_flex), 0)
        FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND fecha_venta BETWEEN %s AND %s
    """, (cuenta_id, desde, hasta))
    ordenes, sin_zona, costo = cursor.fetchone()
    return {"ordenes": int(ordenes or 0), "sin_zona": int(sin_zona or 0), "costo": float(costo or 0)}

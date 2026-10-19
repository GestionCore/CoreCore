"""
Costo de entrega de Flex.

En Flex el vendedor entrega con su propia logística y MeLi reporta costo_envio = 0: el costo real lo cobra esa logística
por zona. Las zonas las define Mercado Libre (ver flex_zonas.py), así que el usuario solo carga lo que le cobra su
logística: "umbrales", cada uno con un precio y las zonas que cubre. Las zonas que no mueve a ningún umbral caen en el
umbral "resto" (siempre existe). cuentas_meli.flex_umbrales guarda los umbrales y cuentas_meli.flex_info lo que se
sincronizó de MeLi (servicio, domicilio de salida y zonas de cobertura).

MeLi le reintegra al vendedor el 10% del envío, así que el costo que se descuenta de la ganancia es el precio del
umbral menos esa bonificación (REINTEGRO_MELI es la de siempre; cada cuenta puede tener la suya en flex_info.reintegro, que
se detecta de lo que informa Mercado Libre de cada envío: ver reintegro_de). La pantalla lo explica.

Lo que informa Mercado Libre de CADA envío (GET /shipments/{id}/costs → senders[0].cost) manda sobre el precio del umbral cuando es $0: paga el
comprador (productos baratos) o lo cubre Mercado Libre (comprador fiel), y a la persona no le cuesta nada. Ese $0 se aplica solo (flex_zona = 0);
el precio de la logística sigue siendo SIEMPRE el que carga la persona (suele coincidir con los anillos de Mercado Libre, pero no tiene por qué).
`detectar_desde_meli` propone esos anillos y sus precios desde los envíos reales; la persona los revisa y los guarda.

ventas.costo_envio es "el envío total que te cuesta": lo que informa MeLi más ventas.costo_flex. Por eso Ganancia Real,
Dashboard, Facturación y el reporte fiscal lo incluyen sin tocar cada cálculo, y por eso toda asignación mueve
costo_flex y costo_envio juntos. ventas.flex_zona es el id del umbral aplicado (0 = sin costo, NULL = pendiente) y
ventas.flex_zona_meli la zona de MeLi donde se ubicó el envío ('*manual' si el usuario eligió el umbral a mano: las
asignaciones manuales y "sin costo" no se tocan al recalcular). Una venta ya valuada conserva su precio salvo que el
usuario pida recalcular.
"""
from datetime import datetime, timezone
import json
import re
import psycopg
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


def neto(precio, reintegro=REINTEGRO_MELI):
    """Lo que de verdad cuesta un envío: el precio de la logística menos la bonificación de MeLi (la de la cuenta, o el 10 % de siempre)."""
    return None if precio is None else round(float(precio) * (1 - reintegro), 2)


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
    reintegro = reintegro_de(config["info"])
    return [{**u, "etiqueta": etiqueta(u, nombres), "neto": neto(u.get("precio"), reintegro)} for u in config["umbrales"]]


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
    previa = obtener_config(cursor, cuenta_id)["info"] or {}
    if previa.get("reintegro") is not None:                  # la bonificación de la cuenta no se pierde al refrescar las zonas
        info["reintegro"] = previa["reintegro"]
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
        SELECT id_orden, MAX(provincia), MAX(localidad), MAX(destino_lat), MAX(destino_lon), MAX(shipment_id)
        FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND {donde}
        GROUP BY id_orden
    """, (cuenta_id,))
    return [{"id_orden": r[0], "provincia": r[1], "localidad": r[2],
             "lat": float(r[3]) if r[3] is not None else None, "lon": float(r[4]) if r[4] is not None else None, "shipment_id": r[5]} for r in cursor.fetchall()]


def umbral_de_familia(umbrales, familia):
    """Umbral que corresponde a una familia de zona: el que la tiene entre sus zonas, y si no, el resto."""
    for u in umbrales:
        if not u.get("resto") and familia and any(fz.familia_de_zona(z) == familia for z in u["zonas"]):
            return u
    return next(u for u in umbrales if u.get("resto"))


def _envios_a_consultar(cursor, cuenta_id, condiciones):
    """Los envíos de las órdenes que se van a valuar: de esos se le pregunta a Mercado Libre cuánto le cuestan al vendedor."""
    return [o["shipment_id"] for donde in condiciones for o in _ordenes(cursor, cuenta_id, donde) if o.get("shipment_id")]


def _plan(cursor, cuenta_id, donde, costos=None):
    """
    ({(umbral_id, familia): [ordenes]}, umbrales, sin_precio) — qué umbral le toca a cada orden, según las zonas de MeLi. Si `costos` (ver costos_meli) dice que Mercado Libre le imputa $0
    al vendedor por ese envío, la orden va al grupo ZONA_SIN_COSTO: no le cuesta nada y no depende de ningún precio.
    """
    umbrales = obtener_config(cursor, cuenta_id)["umbrales"]
    por_grupo, sin_precio = {}, 0
    for o in _ordenes(cursor, cuenta_id, donde):
        informado = (costos or {}).get(str(o["shipment_id"])) if o.get("shipment_id") else None
        if informado is not None and informado["costo"] == 0:
            por_grupo.setdefault((ZONA_SIN_COSTO, None), []).append(o["id_orden"])
            continue
        familia = fz.familia_de_destino(o["provincia"], o["localidad"], o["lat"], o["lon"])
        u = umbral_de_familia(umbrales, familia)
        if u.get("precio") is None:
            sin_precio += 1
        else:
            por_grupo.setdefault((u["id"], familia), []).append(o["id_orden"])
    return por_grupo, umbrales, sin_precio


def vista_previa(cursor, cuenta_id, incluir_valuadas=False, access_token=None):
    """Qué pasaría al aplicar, sin escribir nada: envíos y costo por umbral, y cuántos no le cuestan nada (según Mercado Libre)."""
    condiciones = [_DONDE_PENDIENTES] + ([_DONDE_VALUADAS] if incluir_valuadas else [])
    costos = costos_meli(cursor, cuenta_id, access_token, _envios_a_consultar(cursor, cuenta_id, condiciones))      # sin token solo se usa lo ya consultado (caché)
    conteo, sin_precio, umbrales = {}, 0, None
    for donde in condiciones:
        por_grupo, umbrales, sp = _plan(cursor, cuenta_id, donde, costos)
        sin_precio += sp
        for (uid, _fam), ordenes in por_grupo.items():
            conteo[uid] = conteo.get(uid, 0) + len(ordenes)
    config = obtener_config(cursor, cuenta_id)
    vista = umbrales_para_vista(config)
    filas = [{"id": u["id"], "etiqueta": u["etiqueta"], "ordenes": conteo[u["id"]], "costo": round(conteo[u["id"]] * (u["neto"] or 0), 2)}
             for u in vista if conteo.get(u["id"])]
    sin_costo = conteo.get(ZONA_SIN_COSTO, 0)
    return {"umbrales": filas, "ordenes": sum(f["ordenes"] for f in filas) + sin_costo, "costo_total": round(sum(f["costo"] for f in filas), 2), "sin_precio": sin_precio, "sin_costo_meli": sin_costo}


def aplicar_automatico(cursor, cuenta_id, incluir_valuadas=False, access_token=None):
    """
    Para el sync y cuando el usuario confirma: a cada orden Flex sin umbral se le aplica el que le corresponde según su
    zona (si ese umbral tiene precio). Con incluir_valuadas también se recalculan las ya valuadas con precios viejos
    (salvo las elegidas a mano y las "sin costo"). Devuelve cuántas órdenes se resolvieron.
    """
    total = 0
    condiciones = [_DONDE_PENDIENTES] + ([_DONDE_VALUADAS] if incluir_valuadas else [])
    costos = costos_meli(cursor, cuenta_id, access_token, _envios_a_consultar(cursor, cuenta_id, condiciones))
    reintegro = reintegro_de(obtener_config(cursor, cuenta_id)["info"])
    for donde in condiciones:
        por_grupo, umbrales, _ = _plan(cursor, cuenta_id, donde, costos)
        precios = {u["id"]: u["precio"] for u in umbrales}
        for (uid, familia), ordenes in por_grupo.items():
            if uid == ZONA_SIN_COSTO:
                _aplicar(cursor, cuenta_id, ordenes, ZONA_SIN_COSTO, 0.0, "*meli")
            else:
                _aplicar(cursor, cuenta_id, ordenes, uid, neto(precios[uid], reintegro), familia or "")
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
        precio_neto = neto(umbral["precio"], reintegro_de(obtener_config(cursor, cuenta_id)["info"]))
    _aplicar(cursor, cuenta_id, [str(id_orden)], umbral_id, precio_neto, MANUAL)
    return True, None


# ── Lo que informa Mercado Libre de cada envío (detección de anillos y envíos que no le cuestan nada a la persona) ───────────────────────────

CLAVE_COSTOS_MELI = "flex_costos_envio"
DIAS_CACHE_COSTOS = 90
MAX_ENVIOS_POR_CONSULTA = 400
HILOS_DE_CONSULTA = 8
MUESTRA_DETECCION = 80


def reintegro_de(info):
    """La bonificación de Mercado Libre de ESTA cuenta (fracción de 0 a 0,5): la que se detectó o cargó, o el 10 % de siempre. Puede variar entre vendedores."""
    try:
        valor = float((info or {}).get("reintegro"))
    except (TypeError, ValueError):
        return REINTEGRO_MELI
    return valor if 0 <= valor <= 0.5 else REINTEGRO_MELI


def guardar_reintegro(cursor, cuenta_id, porcentaje):
    """Guarda la bonificación de Mercado Libre de la cuenta (0 a 50 %). Devuelve (ok, error)."""
    try:
        valor = float(str(porcentaje).replace(",", "."))
    except (TypeError, ValueError):
        return False, "La bonificación tiene que ser un número entre 0 y 50."
    if not 0 <= valor <= 50:
        return False, "La bonificación tiene que estar entre 0 y 50 %."
    cursor.execute("UPDATE cuentas_meli SET flex_info = COALESCE(flex_info, '{}'::jsonb) || jsonb_build_object('reintegro', %s::numeric) WHERE id = %s", (round(valor / 100, 4), cuenta_id))
    return True, None


def _costo_de_un_envio(headers, shipment_id):
    """{"costo", "tasa"} de GET /shipments/{id}/costs -> senders[0]: lo que Mercado Libre le imputa al vendedor por ese envío (ya con la bonificación) y la tasa de esa bonificación; None si no se pudo saber."""
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/shipments/{shipment_id}/costs", headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        remitente = (resp.json().get("senders") or [{}])[0]
        if remitente.get("cost") is None:
            return None
        tasa = next((d.get("rate") for d in remitente.get("discounts") or [] if d.get("type") == "mandatory" and d.get("rate") is not None), None)
        return {"costo": float(remitente["cost"]), "tasa": float(tasa) if tasa is not None else None}
    except Exception as e:
        print(f"[Flex] ⚠️ No se pudo consultar el costo del envío {shipment_id}: {e}")
        return None


def costos_meli(cursor, cuenta_id, access_token, shipment_ids):
    """
    {id de envío: {"costo", "tasa"}} para los envíos pedidos. Lo ya consultado sale de `cache_db` (un envío no cambia de costo) y lo que falta se pide a Mercado Libre en paralelo (hasta
    MAX_ENVIOS_POR_CONSULTA por vez). Sin token o si Mercado Libre no contesta, esos envíos simplemente no figuran: quien llama los trata como «no se sabe».
    """
    import cache_db
    from concurrent.futures import ThreadPoolExecutor
    ids = list(dict.fromkeys(str(i) for i in shipment_ids if i))
    if not ids:
        return {}
    hit, guardados = cache_db.leer(cursor, cuenta_id, CLAVE_COSTOS_MELI, firma="", ttl_segundos=DIAS_CACHE_COSTOS * 86400)
    guardados = guardados if hit and isinstance(guardados, dict) else {}
    faltan = [i for i in ids if i not in guardados][:MAX_ENVIOS_POR_CONSULTA]
    if faltan and access_token:
        headers = {"Authorization": f"Bearer {access_token}", "x-format-new": "true"}
        with ThreadPoolExecutor(max_workers=HILOS_DE_CONSULTA) as pool:
            nuevos = list(pool.map(lambda i: _costo_de_un_envio(headers, i), faltan))
        agregados = {i: [r["costo"], r["tasa"]] for i, r in zip(faltan, nuevos) if r}
        if agregados:
            guardados.update(agregados)
            cache_db.guardar(cursor, cuenta_id, CLAVE_COSTOS_MELI, guardados, firma="")
    return {i: {"costo": guardados[i][0], "tasa": guardados[i][1]} for i in ids if i in guardados}


def armar_propuesta(envios, zonas, reintegro_actual=REINTEGRO_MELI):
    """
    De envíos Flex reales ([{"familia", "costo", "tasa"}]: lo que Mercado Libre le imputó al vendedor por cada uno) arma los anillos de precio que hay en su cuenta: los envíos con costo se agrupan por
    el precio de la logística (costo ÷ (1 − bonificación)), de menor a mayor, y cada zona va al anillo donde más envíos tuvo. Los de costo $0 (paga el comprador o lo cubre Mercado Libre) no forman anillos.
    `zonas` es [{"id", "nombre"}] de la cuenta. Devuelve la propuesta que la persona revisa y guarda ella: nada de esto toca una venta.
    """
    pagados = [e for e in envios if e["costo"] and e["costo"] > 0]
    tasas = {}
    for e in pagados:
        if e.get("tasa") is not None:
            tasas[round(e["tasa"], 4)] = tasas.get(round(e["tasa"], 4), 0) + 1
    tasa = max(tasas.items(), key=lambda kv: kv[1])[0] if tasas else reintegro_actual
    por_precio = {}
    for e in pagados:
        bruto = round(e["costo"] / (1 - tasa)) if tasa < 1 else round(e["costo"])
        por_precio.setdefault(bruto, []).append(e)
    precios = sorted(por_precio)
    nombres = {3: ["Zonas cercanas", "Distancia media", "Zonas lejanas"], 2: ["Zonas cercanas", "Zonas lejanas"], 1: ["Todas tus zonas con costo"]}.get(len(precios)) or [f"Anillo {i + 1}" for i in range(len(precios))]
    # cada familia de zona va al anillo donde más envíos tuvo (si empata, al más caro: es lo prudente para el costo)
    conteo = {}
    for bruto, lista in por_precio.items():
        for e in lista:
            if e.get("familia"):
                conteo.setdefault(e["familia"], {}).setdefault(bruto, 0)
                conteo[e["familia"]][bruto] += 1
    elegido, mixtas = {}, []
    for familia, por in conteo.items():
        elegido[familia] = max(por.items(), key=lambda kv: (kv[1], kv[0]))[0]
        if len(por) > 1:
            mixtas.append({"zona": nombre_de_familia(familia, zonas), "reparto": {str(p): n for p, n in sorted(por.items())}, "quedo_en": elegido[familia]})
    umbrales = []
    for nombre, bruto in zip(nombres, precios):
        familias = sorted(f for f, p in elegido.items() if p == bruto)
        ids = [z["id"] for z in zonas if fz.familia_de_zona(z["id"]) in familias]
        umbrales.append({"nombre": nombre, "precio": bruto, "zonas": ids, "envios": len(por_precio[bruto])})
    return {
        "reintegro_pct": round(tasa * 100, 2), "umbrales": umbrales, "precio_del_resto": precios[-1] if precios else None, "envios_analizados": len(envios), "envios_con_costo": len(pagados),
        "envios_sin_costo": len(envios) - len(pagados), "envios_sin_ubicar": sum(1 for e in pagados if not e.get("familia")), "zonas_en_dos_anillos": mixtas,
    }


def nombre_de_familia(familia, zonas):
    """El nombre legible de una familia de zonas («la matanza» → «La Matanza»)."""
    for z in zonas:
        if fz.familia_de_zona(z["id"]) == familia:
            return re.sub(r"\s+\d+$", "", z["nombre"])
    return familia.title()


def detectar_desde_meli(cursor, cuenta_id, access_token):
    """
    Mira los últimos envíos Flex de la cuenta, le pregunta a Mercado Libre cuánto le imputó al vendedor por cada uno y arma los anillos (ver armar_propuesta). Solo LEE: no guarda nada. Devuelve (propuesta, error).
    """
    config = obtener_config(cursor, cuenta_id)
    zonas = (config["info"] or {}).get("zonas") or []
    if not zonas:
        return None, "Primero sincronizá tus zonas con Mercado Libre."
    cursor.execute("""
        SELECT shipment_id, MAX(provincia), MAX(localidad), MAX(destino_lat), MAX(destino_lon) FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service' AND shipment_id IS NOT NULL
        GROUP BY shipment_id ORDER BY MAX(fecha_venta) DESC LIMIT %s
    """, (cuenta_id, MUESTRA_DETECCION))
    filas = cursor.fetchall()
    if not filas:
        return None, "Todavía no hay envíos Flex para analizar."
    costos = costos_meli(cursor, cuenta_id, access_token, [f[0] for f in filas])
    envios = [{"familia": fz.familia_de_destino(f[1], f[2], float(f[3]) if f[3] is not None else None, float(f[4]) if f[4] is not None else None), **costos[str(f[0])]}
              for f in filas if str(f[0]) in costos]
    if not envios:
        return None, "Mercado Libre no devolvió el costo de tus envíos ahora mismo. Probá de nuevo en un rato."
    return armar_propuesta(envios, zonas, reintegro_de(config["info"])), None


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


# ── Envíos Flex que se pagaron y no se recuperan (la orden se entregó y después se canceló o se devolvió) ──────────────────────────────────
ORIGEN_IDA = "flex_ida"
ORIGEN_VUELTA = "flex_vuelta"
_CLAVE_UNICA = "ON CONFLICT (cuenta_id, origen, referencia) WHERE origen IS NOT NULL"


def perdidas_por_orden(filas):
    """
    De las filas de `ventas` que se retiran por cancelación o reembolso [(id_orden, tipo_logistica, despachado, costo_flex, fecha_venta)], lo que ya se pagó de entrega Flex y no se
    recupera: [(id_orden, costo, fecha_venta)] de las órdenes entregadas con logística propia (Flex) y con costo de entrega cargado. Una orden cancelada ANTES de salir no costó nada
    (`despachado` falso) y una sin costo asignado no se inventa: se suma el costo de todos los ítems de la orden. Es el mismo costo que ya contaba en tu ganancia mientras la orden vivía.
    """
    por_orden = {}
    for id_orden, tipo_logistica, despachado, costo_flex, fecha_venta in filas:
        if tipo_logistica != "self_service" or not despachado or not costo_flex or float(costo_flex) <= 0:
            continue
        previo = por_orden.get(id_orden, (0.0, fecha_venta))
        por_orden[id_orden] = (previo[0] + float(costo_flex), previo[1])
    return [(id_orden, round(costo, 2), fecha) for id_orden, (costo, fecha) in por_orden.items()]


def registrar_envios_perdidos(cursor, cuenta_id, filas, hoy):
    """
    Registra como GASTO OPERATIVO irrecuperable el envío Flex de ida de cada orden entregada y luego cancelada o devuelta (ver perdidas_por_orden). Se anota en la fecha de HOY (cuando
    se supo), no en la de la venta: así no se reescribe un período ya cerrado. Una sola vez por orden (clave única): repetirlo no duplica nada. Devuelve cuántos gastos nuevos anotó.
    """
    nuevos = 0
    for id_orden, costo, fecha_venta in perdidas_por_orden(filas):
        cursor.execute(f"""
            INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha, origen, referencia)
            VALUES (%s, %s, 'variable', %s, %s, %s, %s) {_CLAVE_UNICA} DO NOTHING
        """, (cuenta_id, f"Envío Flex de ida · orden {id_orden} (devuelta o cancelada, no se recupera)", costo, hoy, ORIGEN_IDA, str(id_orden)))
        nuevos += cursor.rowcount
    return nuevos


def envios_perdidos(cursor, cuenta_id, desde, hasta):
    """
    Los envíos Flex de órdenes devueltas o canceladas del período, con el costo de ida que se registró solo y el de vuelta que cargó la persona (None si no cargó):
    [{"id_orden", "fecha", "ida", "vuelta"}]. [] si todavía no existe la columna de origen (migración 0049 pendiente).
    """
    try:
        with cursor.connection.transaction():
            cursor.execute("""
                SELECT i.referencia, i.fecha, i.monto, v.monto
                FROM gastos_operativos i
                LEFT JOIN gastos_operativos v ON v.cuenta_id = i.cuenta_id AND v.origen = %s AND v.referencia = i.referencia
                WHERE i.cuenta_id = %s AND i.origen = %s AND i.fecha BETWEEN %s AND %s
                ORDER BY i.fecha DESC, i.id DESC
            """, (ORIGEN_VUELTA, cuenta_id, ORIGEN_IDA, desde, hasta))
            filas = cursor.fetchall()
    except psycopg.errors.UndefinedColumn:
        return []
    return [{"id_orden": ref, "fecha": f, "ida": float(ida), "vuelta": float(vuelta) if vuelta is not None else None} for ref, f, ida, vuelta in filas]


def guardar_costo_de_vuelta(cursor, cuenta_id, id_orden, monto, hoy):
    """
    Anota (o corrige, o quita con 0) lo que costó el envío de VUELTA de una orden Flex devuelta, como otro gasto operativo irrecuperable. Solo para órdenes que ya figuran entre los envíos
    Flex devueltos o cancelados de la cuenta. Devuelve (ok, mensaje).
    """
    try:
        monto = round(float(monto), 2)
    except (TypeError, ValueError):
        return False, "Ingresá un monto válido."
    if not 0 <= monto <= TOPE_PRECIO or monto != monto:
        return False, f"El monto tiene que estar entre $0 y ${TOPE_PRECIO:,}.".replace(",", ".")
    id_orden = str(id_orden or "").strip()
    try:
        with cursor.connection.transaction():
            cursor.execute("SELECT 1 FROM gastos_operativos WHERE cuenta_id = %s AND origen = %s AND referencia = %s", (cuenta_id, ORIGEN_IDA, id_orden))
            if not cursor.fetchone():
                return False, "Esa orden no está entre tus envíos Flex devueltos o cancelados."
            if monto == 0:
                cursor.execute("DELETE FROM gastos_operativos WHERE cuenta_id = %s AND origen = %s AND referencia = %s", (cuenta_id, ORIGEN_VUELTA, id_orden))
                return True, "Quitamos el costo de vuelta."
            cursor.execute(f"""
                INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha, origen, referencia)
                VALUES (%s, %s, 'variable', %s, %s, %s, %s) {_CLAVE_UNICA} DO UPDATE SET monto = excluded.monto
            """, (cuenta_id, f"Envío Flex de vuelta · orden {id_orden} (devolución, no se recupera)", monto, hoy, ORIGEN_VUELTA, id_orden))
            return True, "Guardamos el costo de vuelta."
    except psycopg.errors.UndefinedColumn:                           # la migración 0049 todavía no se aplicó: todavía no hay envíos perdidos que corregir
        return False, "Esta función se activa con la próxima actualización de CoreLux."

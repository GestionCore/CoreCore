"""
Monitor en vivo: lo de HOY en una sola pantalla — ventas e ingresos por hora, visitas, conversión y publicidad — siempre en neto (sin lo que se canceló o devolvió).

Qué da Mercado Libre y qué no (verificado contra la API real, 2026-10-13):
  · Ventas: CoreLux las tiene con su hora (tabla `ventas`): la curva por hora es exacta.
  · Publicidad (Product Ads) y visitas: la API las informa POR DÍA, nunca por hora (`aggregation_type` solo admite CAMPAIGN y DAILY; `unit=hour` se ignora y devuelve
    días). Pero SÍ da el acumulado de hoy en tiempo real. Por eso CoreLux ANOTA ese acumulado cada ~30 minutos (tabla `monitor_snapshots`, migración 0048) y la curva por
    hora es la diferencia entre dos anotaciones seguidas, repartida en las horas que abarca. Lo que pasó antes de la primera anotación del día no se le asigna a ninguna
    hora (se sabe cuánto fue en total, no cuándo), y cada hora lleva `cubierta` = qué parte de la hora se midió de verdad: la pantalla lo dice, no lo disimula.
Si la tabla todavía no existe (migración pendiente) o Mercado Libre no contesta, todo sigue funcionando: sin curva, con el total del día.
Todo se lee y escribe con la conexión del usuario (RLS por cuenta).
"""
import json
from datetime import datetime, timedelta

import psycopg

import ads
import db
import meli_http
from utils import ARGENTINA, hoy_argentina, sql_momento_argentina

INTERVALO_ANOTACION_MINUTOS = 10       # la pantalla anota si lo último guardado tiene más que esto (el scheduler lo hace cada 30)
DIAS_ANOTACIONES = 3                   # las anotaciones más viejas se borran: solo importa el día de hoy


# ── Ventas por hora (exactas, de la base) ──────────────────────────────────────────────────────────────────────────────────────────────

def _vacio():
    return {"ordenes": 0, "unidades": 0, "facturado": 0.0}


def ventas_por_hora(cursor, fecha):
    """
    Las 24 horas del día `fecha` con lo vendido NETO (`ventas`) y lo cancelado o devuelto (`ventas_retiradas`, la misma línea archivada dos veces cuenta una):
    [{"hora": 0..23, "netas": {ordenes, unidades, facturado}, "canceladas": {...}}]. La hora es la de Argentina (utils.sql_momento_argentina para las filas viejas).
    """
    cursor.execute(f"""
        WITH dia AS (
            SELECT 'neta' AS estado, EXTRACT(HOUR FROM {sql_momento_argentina()})::int AS hora, id_orden, cantidad, precio_venta * cantidad AS monto
            FROM ventas WHERE fecha_venta = %(fecha)s
            UNION ALL
            SELECT 'cancelada',
                   EXTRACT(HOUR FROM (r.fila->>'fecha_venta')::date + COALESCE((r.fila->>'hora_venta')::time, TIME '00:00')
                           + CASE WHEN COALESCE((r.fila->>'hora_normalizada')::boolean, true) THEN INTERVAL '0 hour' ELSE INTERVAL '1 hour' END)::int,
                   r.id_orden, COALESCE((r.fila->>'cantidad')::int, 1),
                   COALESCE((r.fila->>'precio_venta')::numeric, 0) * COALESCE((r.fila->>'cantidad')::int, 1)
            FROM (SELECT DISTINCT ON (id_orden, fila->>'id_meli') * FROM ventas_retiradas
                  WHERE (fila->>'fecha_venta')::date = %(fecha)s ORDER BY id_orden, fila->>'id_meli', id) r
        )
        SELECT estado, hora, COUNT(DISTINCT id_orden), COALESCE(SUM(cantidad), 0), COALESCE(SUM(monto), 0) FROM dia GROUP BY estado, hora
    """, {"fecha": fecha})
    horas = [{"hora": h, "netas": _vacio(), "canceladas": _vacio()} for h in range(24)]
    for estado, hora, ordenes, unidades, monto in cursor.fetchall():
        if hora is None or not 0 <= int(hora) <= 23:
            continue
        horas[int(hora)]["netas" if estado == "neta" else "canceladas"] = {"ordenes": int(ordenes), "unidades": int(unidades), "facturado": round(float(monto), 2)}
    return horas


def momentos_de_ordenes_netas(cursor, fecha):
    """La hora (datetime argentino, sin zona) de cada orden NETA del día, ordenadas: sirve para contar cuántas había hasta cada anotación de visitas."""
    cursor.execute(f"SELECT MIN({sql_momento_argentina()}) FROM ventas WHERE fecha_venta = %s GROUP BY id_orden ORDER BY 1", (fecha,))
    return [m for (m,) in cursor.fetchall() if m is not None]


# ── Curvas por hora a partir de acumulados anotados ────────────────────────────────────────────────────────────────────────────────────

def curva_por_hora(puntos):
    """
    `puntos` = [(datetime argentino con zona, acumulado del día)] ordenados. Lo que sumó cada intervalo (el acumulado no baja: una baja se toma como 0) se reparte
    entre las horas que abarca, en proporción al tiempo. Devuelve 24 {"hora", "valor", "cubierta"}: `cubierta` es la parte de la hora (0 a 1) que se midió.
    Antes del primer punto no se le asigna nada a ninguna hora: el acumulado inicial dice cuánto fue en total, no cuándo.
    """
    valores, cubiertas = [0.0] * 24, [0.0] * 24
    for (t0, v0), (t1, v1) in zip(puntos, puntos[1:]):
        total = (t1 - t0).total_seconds()
        if total <= 0:
            continue
        delta = max(float(v1) - float(v0), 0.0)
        t = t0
        while t < t1:
            fin_hora = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            tramo_fin = min(t1, fin_hora)
            segundos = (tramo_fin - t).total_seconds()
            valores[t.hour] += delta * segundos / total
            cubiertas[t.hour] += segundos / 3600
            t = tramo_fin
    return [{"hora": h, "valor": round(valores[h], 2), "cubierta": round(min(cubiertas[h], 1.0), 2)} for h in range(24)]


def _inicio_del_dia(fecha):
    return datetime.strptime(str(fecha)[:10], "%Y-%m-%d").replace(tzinfo=ARGENTINA)


def armar_curvas(anotaciones):
    """
    De las anotaciones del día [(momento con zona, tipo, clave, datos)] a las curvas: la cuenta entera y cada campaña (impresiones, clics, unidades, plata, gasto) y las visitas.
    También devuelve los puntos de visitas acumuladas ({"momento", "visitas"}) para la conversión, y cuántas anotaciones hay.
    """
    por_campana, visitas, momentos = {}, [], set()
    for momento, tipo, clave, datos in anotaciones:
        momentos.add(momento)
        if tipo == "visitas":
            visitas.append((momento, float(datos.get("visitas") or 0)))
        elif tipo == "ads":
            por_campana.setdefault(clave, {"nombre": datos.get("nombre") or clave, "filas": {}})["filas"][momento] = datos
    campos = (("impresiones", "impresiones"), ("clics", "clics"), ("unidades", "unidades"), ("monto", "monto"), ("costo", "costo"))
    instantes = sorted(momentos)
    curvas = {}
    for clave, c in por_campana.items():
        curvas[clave] = {"nombre": c["nombre"], **{campo: curva_por_hora([(t, float(c["filas"].get(t, {}).get(campo) or 0)) for t in instantes]) for campo, _ in campos}}
    if curvas:                                 # la cuenta entera = la suma de sus campañas en cada instante
        total = {campo: curva_por_hora([(t, sum(float(c["filas"].get(t, {}).get(campo) or 0) for c in por_campana.values())) for t in instantes]) for campo, _ in campos}
        curvas["*"] = {"nombre": "Toda la cuenta", **total}
    visitas.sort()
    return {"curvas": curvas, "curva_visitas": curva_por_hora(visitas) if visitas else None,
            "puntos_visitas": [{"momento": m.isoformat(), "visitas": int(v)} for m, v in visitas], "anotaciones": len(instantes),
            "desde": instantes[0].astimezone(ARGENTINA).strftime("%H:%M") if instantes else None}


def conversion_acumulada(puntos_visitas, momentos_ordenes):
    """
    La conversión del día en cada anotación de visitas: órdenes NETAS hasta ese momento ÷ visitas acumuladas. [{"hora": "14:30", "visitas", "ordenes", "conversion": %}].
    `momentos_ordenes` = hora (datetime argentino sin zona) de cada orden neta, ordenadas. Sin visitas todavía no hay conversión: se omite el punto.
    """
    salida = []
    for p in puntos_visitas:
        momento = datetime.fromisoformat(p["momento"]).astimezone(ARGENTINA).replace(tzinfo=None)
        visitas = int(p["visitas"])
        if visitas <= 0:
            continue
        ordenes = sum(1 for m in momentos_ordenes if m <= momento)
        salida.append({"hora": momento.strftime("%H:%M"), "visitas": visitas, "ordenes": ordenes, "conversion": round(ordenes / visitas * 100, 2)})
    return salida


# ── Anotaciones (tabla monitor_snapshots) ──────────────────────────────────────────────────────────────────────────────────────────────

def _falta_la_tabla(error):
    return isinstance(error, psycopg.errors.UndefinedTable)


def leer_anotaciones(usuario_id, cuenta_id, fecha):
    """Las anotaciones del día (hora argentina) [(momento, tipo, clave, datos)], o None si la tabla todavía no existe (migración 0048 pendiente)."""
    inicio = _inicio_del_dia(fecha)
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT momento, tipo, clave, datos FROM monitor_snapshots WHERE cuenta_id = %s AND momento >= %s AND momento < %s ORDER BY momento",
                           (cuenta_id, inicio, inicio + timedelta(days=1)))
            return [(m.astimezone(ARGENTINA), tipo, clave, datos) for m, tipo, clave, datos in cursor.fetchall()]
    except psycopg.errors.UndefinedTable:
        return None


def _ultima_anotacion(usuario_id, cuenta_id):
    """Cuándo fue la última anotación (datetime con zona), None si no hay o si la tabla no existe."""
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT MAX(momento) FROM monitor_snapshots WHERE cuenta_id = %s", (cuenta_id,))
            return cursor.fetchone()[0]
    except psycopg.errors.UndefinedTable:
        return None


def guardar_anotacion(usuario_id, cuenta_id, campanas, visitas, ahora=None):
    """
    Guarda el acumulado de hoy: una fila por campaña con actividad (`campanas` = lo que devuelve ads.obtener_campanas_con_metricas) y una de visitas. Todas con el MISMO
    momento: así se reconocen como una sola anotación. Borra las de más de DIAS_ANOTACIONES días. Devuelve cuántas filas guardó (0 si la tabla no existe).
    """
    ahora = ahora or datetime.now(ARGENTINA)
    filas = []
    for c in campanas or []:
        if (c.get("prints") or 0) > 0 or (c.get("clicks") or 0) > 0 or (c.get("costo") or 0) > 0 or (c.get("unidades") or 0) > 0:
            filas.append(("ads", str(c["id"]), {"nombre": c.get("nombre"), "impresiones": int(c.get("prints") or 0), "clics": int(c.get("clicks") or 0), "costo": round(float(c.get("costo") or 0), 2),
                                                "unidades": int(c.get("unidades") or 0), "monto": round(float(c.get("ventas_atribuidas") or 0), 2)}))
    if visitas is not None:
        filas.append(("visitas", "", {"visitas": int(visitas)}))
    if not filas:
        return 0
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for tipo, clave, datos in filas:
                cursor.execute("INSERT INTO monitor_snapshots (cuenta_id, momento, tipo, clave, datos) VALUES (%s, %s, %s, %s, %s::jsonb)", (cuenta_id, ahora, tipo, clave, json.dumps(datos)))
            cursor.execute("DELETE FROM monitor_snapshots WHERE cuenta_id = %s AND momento < %s", (cuenta_id, ahora - timedelta(days=DIAS_ANOTACIONES)))
        return len(filas)
    except psycopg.errors.UndefinedTable:
        return 0


# ── Lo que informa Mercado Libre ahora (acumulado de hoy) ──────────────────────────────────────────────────────────────────────────────

def visitas_de_la_cuenta(access_token, meli_user_id):
    """
    {"hoy": n, "ayer": n} de las visitas a TODAS las publicaciones, por día (Mercado Libre no las da por hora). None si no contestó: no es lo mismo que cero visitas.
    Si el último día que informa no es el de hoy en Argentina (cerca de la medianoche las fechas pueden no coincidir) «hoy» queda en None en vez de mostrar el de ayer.
    """
    hoy = hoy_argentina()
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/users/{meli_user_id}/items_visits/time_window", headers={"Authorization": f"Bearer {access_token}"},
                             params={"last": 2, "unit": "day"}, timeout=15)
        if resp.status_code != 200:
            print(f"[Monitor] ⚠️ Visitas: {resp.status_code} - {resp.text[:200]}")
            return None
        por_dia = {str(r.get("date", ""))[:10]: int(r.get("total") or 0) for r in (resp.json().get("results") or [])}
    except Exception as e:
        print(f"[Monitor] ⚠️ No se pudieron leer las visitas: {e}")
        return None
    return {"hoy": por_dia.get(hoy.isoformat()), "ayer": por_dia.get((hoy - timedelta(days=1)).isoformat())}


def _id_de_meli(usuario_id, cuenta_id):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
    return fila[0] if fila else None


def medir_ahora(usuario_id, cuenta_id, access_token):
    """
    Lo que Mercado Libre informa AHORA de hoy: {"campanas": [...] o None si no se pudo (o no hay Publicidad), "visitas": {"hoy", "ayer"} o None}.
    """
    advertiser_id = ads.obtener_advertiser_id(access_token, cuenta_id) if access_token else None
    hoy = hoy_argentina().isoformat()
    campanas = ads.obtener_campanas_con_metricas(access_token, advertiser_id, hoy, hoy, estricto=True) if advertiser_id else None
    meli_user_id = _id_de_meli(usuario_id, cuenta_id) if access_token else None
    visitas = visitas_de_la_cuenta(access_token, meli_user_id) if meli_user_id else None
    return {"campanas": campanas, "visitas": visitas, "con_publicidad": bool(advertiser_id)}


def tomar_anotacion(usuario_id, cuenta_id, access_token):
    """Mide y guarda (lo que hace el scheduler cada 30 minutos). Devuelve las filas guardadas."""
    medicion = medir_ahora(usuario_id, cuenta_id, access_token)
    visitas = (medicion["visitas"] or {}).get("hoy")
    return guardar_anotacion(usuario_id, cuenta_id, medicion["campanas"], visitas)


def anotar_si_hace_falta(usuario_id, cuenta_id, medicion, ahora=None):
    """Quien abre el Monitor también anota (si lo último tiene más de INTERVALO_ANOTACION_MINUTOS): así la curva se arma sola aunque el scheduler no haya corrido."""
    ahora = ahora or datetime.now(ARGENTINA)
    ultima = _ultima_anotacion(usuario_id, cuenta_id)
    if ultima is not None and (ahora - ultima).total_seconds() < INTERVALO_ANOTACION_MINUTOS * 60:
        return 0
    return guardar_anotacion(usuario_id, cuenta_id, medicion["campanas"], (medicion["visitas"] or {}).get("hoy"), ahora)


def resumen_de_publicidad(campanas):
    """Los totales de hoy de la cuenta (impresiones, clics, CTR, gasto, unidades, ventas por anuncios) y las campañas con actividad, la que más gastó primero."""
    activas = [c for c in campanas if (c.get("prints") or 0) > 0 or (c.get("clicks") or 0) > 0 or (c.get("costo") or 0) > 0]
    impresiones, clics = sum(int(c.get("prints") or 0) for c in campanas), sum(int(c.get("clicks") or 0) for c in campanas)
    gasto = round(sum(float(c.get("costo") or 0) for c in campanas), 2)
    return {
        "impresiones": impresiones, "clics": clics, "ctr": round(clics / impresiones * 100, 2) if impresiones else 0.0, "gasto": gasto,
        "unidades": sum(int(c.get("unidades") or 0) for c in campanas), "ventas_atribuidas": round(sum(float(c.get("ventas_atribuidas") or 0) for c in campanas), 2),
        "campanas": [{"id": str(c["id"]), "nombre": c.get("nombre"), "estado": c.get("estado"), "impresiones": int(c.get("prints") or 0), "clics": int(c.get("clicks") or 0),
                      "gasto": round(float(c.get("costo") or 0), 2), "unidades": int(c.get("unidades") or 0)} for c in sorted(activas, key=lambda c: -float(c.get("costo") or 0))],
    }


def datos_de_medicion(usuario_id, cuenta_id, access_token, ahora=None):
    """
    Lo que alimenta los paneles de publicidad y visitas del Monitor: lo que Mercado Libre informa ahora (guardado 60 s en cache_db), las curvas por hora armadas con las
    anotaciones del día y la conversión. Si la persona abre el Monitor y hace rato que no se anota nada, anota (así la curva se arma sola).
    {"publicidad": {...} o None, "visitas": {...} o None, "anotaciones": n, "medido_desde": "HH:MM" o None, "tabla": bool (False = migración 0048 pendiente)}
    """
    import cache_db
    ahora = ahora or datetime.now(ARGENTINA)
    hoy = ahora.date().isoformat()
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        hit, medicion = cache_db.leer(cursor, cuenta_id, "monitor_medicion", firma=hoy, ttl_segundos=60, ttl_fallido=20)
        momentos_ordenes = momentos_de_ordenes_netas(cursor, hoy)
    if not hit or medicion is None:
        medicion = medir_ahora(usuario_id, cuenta_id, access_token)
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cache_db.guardar(conexion.cursor(), cuenta_id, "monitor_medicion", medicion, firma=hoy)
        anotar_si_hace_falta(usuario_id, cuenta_id, medicion, ahora)
    anotaciones = leer_anotaciones(usuario_id, cuenta_id, hoy)
    armado = armar_curvas(anotaciones or [])
    campanas = medicion.get("campanas")
    publicidad = None
    if campanas is not None:
        publicidad = {**resumen_de_publicidad(campanas), "curvas": armado["curvas"]}
    visitas = None
    if medicion.get("visitas"):
        v = medicion["visitas"]
        visitas = {"hoy": v.get("hoy"), "ayer": v.get("ayer"), "curva": armado["curva_visitas"],
                   "conversion": conversion_acumulada(armado["puntos_visitas"], momentos_ordenes), "ordenes_netas": len(momentos_ordenes),
                   "conversion_actual": round(len(momentos_ordenes) / v["hoy"] * 100, 2) if v.get("hoy") else None}
    return {"fecha": hoy, "con_publicidad": bool(medicion.get("con_publicidad")), "publicidad": publicidad, "visitas": visitas,
            "anotaciones": armado["anotaciones"], "medido_desde": armado["desde"], "tabla": anotaciones is not None, "actualizado": ahora.strftime("%H:%M:%S")}


def ganancia_por_hora(ventas):
    """
    La ganancia neta real de cada hora de hoy a partir de las ventas de calcular_ganancia_real (cada una lleva su `momento` en hora argentina y `raw.ganancia_neta`).
    Son ventas netas: lo cancelado ya no está. [{"hora", "ganancia", "ventas"}] y el total.
    """
    horas = [{"hora": h, "ganancia": 0.0, "ventas": 0} for h in range(24)]
    for v in ventas:
        if not v.get("momento"):
            continue
        h = datetime.fromisoformat(v["momento"]).hour
        horas[h]["ganancia"] += float(v["raw"]["ganancia_neta"])
        horas[h]["ventas"] += 1
    for fila in horas:
        fila["ganancia"] = round(fila["ganancia"], 2)
    return {"por_hora": horas, "total": round(sum(f["ganancia"] for f in horas), 2)}


def ganancia_de_hoy_por_hora(usuario_id, cuenta_id, access_token):
    """La ganancia neta real de hoy hora por hora (la fórmula completa de metricas.calcular_ganancia_real); se guarda 2 minutos en cache_db porque consulta la API de Publicidad."""
    import cache_db
    import metricas
    hoy = hoy_argentina().isoformat()
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        hit, datos = cache_db.leer(conexion.cursor(), cuenta_id, "monitor_ganancia", firma=hoy, ttl_segundos=120, ttl_fallido=30)
    if hit and datos is not None:
        return datos
    datos = {**ganancia_por_hora(metricas.calcular_ganancia_real(usuario_id, cuenta_id, access_token, hoy, hoy)["ventas"]), "fecha": hoy}
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cache_db.guardar(conexion.cursor(), cuenta_id, "monitor_ganancia", datos, firma=hoy)
    return datos

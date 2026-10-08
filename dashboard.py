"""
Dashboard personalizable — portado de Santi Mens. Nota real de traducción:
el original usaba `fecha_venta LIKE 'YYYY-MM-DD%'` para matchear "hoy",
porque en SQLite fecha_venta a veces llevaba el timestamp completo como
texto. Acá fecha_venta es un DATE limpio (sin hora), así que un simple
`= %s` alcanza y es más correcto.
"""
from datetime import datetime, timedelta, timezone
import db
import analisis_stock
import salud_cuenta
import resumen_semanal
from utils import ARGENTINA, formatear_moneda, hoy_argentina, limpiar_titulo_modelo, extraer_talle, SQL_RECLAMO_AFECTA, sql_momento_argentina


def _detalle_venta(titulo):
    modelo = limpiar_titulo_modelo(titulo)
    talle = extraer_talle(titulo)
    return modelo if talle == "Único" else f"{modelo} ({talle})"


def top_modelos(filas, maximo=5):
    """
    Los modelos que más facturaron, con todos sus talles/variantes JUNTOS (la clave de modelo es utils.limpiar_titulo_modelo). Cada fila:
    (titulo, id_meli, unidades, facturado, miniatura, existe_en_la_base). La foto y la publicación que abre el panel son las de la publicación del
    modelo que más facturó; `pct` es la parte del total facturado (de TODOS los modelos, no solo de los que se muestran).
    """
    modelos = {}
    for titulo, id_meli, unidades, facturado, miniatura, existe in filas:
        nombre = limpiar_titulo_modelo(titulo) or "Sin nombre"
        m = modelos.setdefault(nombre.lower(), {"nombre": nombre, "unidades": 0, "facturado": 0.0, "publicaciones": 0, "mejor": -1.0, "id_meli": None, "miniatura": None})
        facturado = float(facturado or 0)
        m["unidades"] += int(unidades or 0)
        m["facturado"] += facturado
        m["publicaciones"] += 1
        if facturado > m["mejor"]:
            m["mejor"], m["miniatura"], m["id_meli"] = facturado, miniatura, (id_meli if existe else None)
    total = sum(m["facturado"] for m in modelos.values()) or 1
    top = sorted(modelos.values(), key=lambda m: -m["facturado"])[:maximo]
    return [{**{k: m[k] for k in ("nombre", "unidades", "facturado", "publicaciones", "id_meli", "miniatura")}, "pct": round(m["facturado"] / total * 100)} for m in top]


def ganancia_de_ayer_hasta_la_hora(ventas, ahora):
    """
    Ganancia neta de AYER entre las 00:00 y esta misma hora, para comparar la mañana de hoy con una mañana (contra el promedio del día entero,
    toda mañana parece floja). `ventas` son las de calcular_ganancia_real (llevan "momento" en hora argentina y raw.ganancia_neta); `ahora` es la
    hora argentina de hoy. Devuelve (ganancia, cantidad de ventas).
    """
    corte = (ahora - timedelta(days=1)).replace(tzinfo=None)
    inicio = corte.replace(hour=0, minute=0, second=0, microsecond=0)
    ganancia, cantidad = 0.0, 0
    for v in ventas:
        if not v.get("momento"):
            continue
        if inicio <= datetime.fromisoformat(v["momento"]) <= corte:
            ganancia += v["raw"]["ganancia_neta"]
            cantidad += 1
    return round(ganancia, 2), cantidad


def obtener_ventas_hoy(usuario_id, cuenta_id=None):
    arg_now = datetime.now(ARGENTINA)
    hoy_local = arg_now.strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT titulo, id_variante, cantidad, precio_venta, hora_venta, id_orden, id_meli
            FROM ventas WHERE fecha_venta = %s ORDER BY id DESC
        """, (hoy_local,))
        ventas_hoy = cursor.fetchall()

        cursor.execute("""
            SELECT COALESCE(SUM(precio_venta * cantidad), 0), COALESCE(SUM(cantidad), 0), COUNT(DISTINCT id_orden)
            FROM ventas WHERE fecha_venta = %s
        """, (hoy_local,))
        facturado_hoy, unidades_hoy, ordenes_hoy = cursor.fetchone()

    lista_ventas = []
    for titulo, id_variante, cant, precio_unitario, hora_venta, id_orden, id_meli in ventas_hoy:
        hora_str = hora_venta.strftime("%H:%M") if hasattr(hora_venta, "strftime") else (hora_venta or arg_now.strftime("%H:%M"))
        lista_ventas.append({
            "id_venta": f"{id_orden}_{id_variante}", "id_orden": id_orden, "titulo": _detalle_venta(titulo),
            "cantidad": cant, "precio": formatear_moneda(cant * float(precio_unitario)), "hora": hora_str,
            "link_meli": f"https://myaccount.mercadolibre.com.ar/sales/{id_orden}/detail"
        })

    return {
        "facturado_hoy": formatear_moneda(facturado_hoy), "unidades_hoy": unidades_hoy,
        "ordenes_hoy": ordenes_hoy, "ultimas_ventas": lista_ventas
    }


def obtener_ventas_por_provincia(usuario_id, cuenta_id=None, dias=30):
    """
    Ranking de provincias por facturación (F1). `provincia` sale del
    envío de MeLi — ventas manuales o ventas ya sincronizadas antes de
    que se empezara a guardar este dato quedan afuera del ranking
    (NULL), no se cuentan como "Sin dato" para no inflar ninguna barra.
    """
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT provincia, COUNT(DISTINCT id_orden) AS ventas, COALESCE(SUM(precio_venta * cantidad), 0) AS facturado
            FROM ventas
            WHERE fecha_venta >= %s AND origen = 'meli' AND provincia IS NOT NULL AND eliminado_en IS NULL
            GROUP BY provincia
            ORDER BY facturado DESC
        """, (desde,))
        filas = cursor.fetchall()

    if not filas:
        return None
    total_facturado = sum(float(f[2]) for f in filas)
    return [
        {
            "provincia": f[0], "ventas": int(f[1]), "facturado_formateado": formatear_moneda(f[2]),
            "pct": round(float(f[2]) / total_facturado * 100, 1) if total_facturado else 0,
        }
        for f in filas
    ]


DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MIN_ORDENES_CUANDO_COMPRAN = 30     # con menos ventas el patrón no dice nada


def obtener_cuando_compran(usuario_id, cuenta_id=None, dias=90):
    """
    Cuándo te compran: ventas por día de la semana y por hora del día (hora argentina). Las ventas viejas guardan la hora de Mercado
    Libre en UTC-4 y las nuevas ya en hora argentina: utils.sql_momento_argentina las unifica. Devuelve None si hay muy pocas ventas.
    """
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT EXTRACT(ISODOW FROM {momento})::int,
                   EXTRACT(HOUR FROM {momento})::int,
                   COUNT(DISTINCT id_orden), COALESCE(SUM(precio_venta * cantidad), 0)
            FROM ventas
            WHERE fecha_venta >= %s AND origen = 'meli' AND hora_venta IS NOT NULL AND eliminado_en IS NULL
            GROUP BY 1, 2
        """.format(momento=sql_momento_argentina()), (desde,))
        filas = cursor.fetchall()
    total = sum(int(f[2]) for f in filas)
    if total < MIN_ORDENES_CUANDO_COMPRAN:
        return None
    por_dia = [{"nombre": DIAS_SEMANA[i], "ordenes": 0, "facturado": 0.0} for i in range(7)]
    por_hora = [{"hora": h, "ordenes": 0} for h in range(24)]
    for dia, hora, n, fact in filas:
        por_dia[dia - 1]["ordenes"] += int(n)
        por_dia[dia - 1]["facturado"] += float(fact)
        por_hora[hora]["ordenes"] += int(n)
    maximo_dia = max(d["ordenes"] for d in por_dia) or 1
    maximo_hora = max(h["ordenes"] for h in por_hora) or 1
    for d in por_dia:
        d["pct"] = round(d["ordenes"] / maximo_dia * 100)
        d["pct_total"] = round(d["ordenes"] / total * 100)
        d["facturado_formateado"] = formatear_moneda(d["facturado"])
    for h in por_hora:
        h["alto"] = max(round(h["ordenes"] / maximo_hora * 100), 2) if h["ordenes"] else 0
    # La mejor franja de 3 horas seguidas (puede cruzar la medianoche)
    mejor = max(range(24), key=lambda h: sum(por_hora[(h + k) % 24]["ordenes"] for k in range(3)))
    return {
        "dias": por_dia, "horas": por_hora, "total": total, "desde_dias": dias,
        "mejor_dia": max(por_dia, key=lambda d: d["ordenes"])["nombre"],
        "peor_dia": min(por_dia, key=lambda d: d["ordenes"])["nombre"],
        "franja": f"{mejor:02d} a {(mejor + 3) % 24:02d} h",
        "pct_franja": round(sum(por_hora[(mejor + k) % 24]["ordenes"] for k in range(3)) / total * 100),
    }


MIN_DIAS_PROYECCION = 3      # con menos días de datos el ritmo no dice nada


def serie_acumulada(por_dia, inicio, hoy, inicio_anterior, fin_anterior):
    """
    Facturación acumulada día por día del mes en curso (hasta hoy) y del mes anterior (completo), para dibujarlos uno sobre otro.
    `por_dia` es {fecha: facturado}. Cada lista arranca en el día 1; la del mes en curso termina hoy, la del anterior en su último día.
    """
    def acumular(desde, hasta):
        total, serie, dia = 0.0, [], desde
        while dia <= hasta:
            total += por_dia.get(dia, 0.0)
            serie.append(round(total, 2))
            dia += timedelta(days=1)
        return serie
    return {"actual": acumular(inicio, hoy), "anterior": acumular(inicio_anterior, fin_anterior)}


def obtener_proyeccion_mes(usuario_id, cuenta_id=None, hoy=None):
    """
    Cómo viene el mes: lo facturado hasta hoy, a cuánto llegaría con el mismo ritmo y cómo se compara con el mes anterior (completo y
    en el mismo punto del mes). La proyección es lineal (ritmo diario actual x días del mes): un orden de magnitud, no una promesa.
    """
    import calendar
    hoy = hoy or hoy_argentina()
    inicio = hoy.replace(day=1)
    dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    fin_anterior = inicio - timedelta(days=1)
    inicio_anterior = fin_anterior.replace(day=1)
    mismo_punto = inicio_anterior + timedelta(days=min(hoy.day, fin_anterior.day) - 1)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(precio_venta * cantidad) FILTER (WHERE fecha_venta >= %(i)s), 0),
                   COALESCE(SUM(cantidad) FILTER (WHERE fecha_venta >= %(i)s), 0),
                   COALESCE(SUM(precio_venta * cantidad) FILTER (WHERE fecha_venta BETWEEN %(ia)s AND %(fa)s), 0),
                   COALESCE(SUM(precio_venta * cantidad) FILTER (WHERE fecha_venta BETWEEN %(ia)s AND %(mp)s), 0),
                   COALESCE(SUM(cantidad) FILTER (WHERE fecha_venta BETWEEN %(ia)s AND %(fa)s), 0)
            FROM ventas WHERE origen = 'meli' AND eliminado_en IS NULL AND fecha_venta >= %(ia)s
        """, {"i": inicio, "ia": inicio_anterior, "fa": fin_anterior, "mp": mismo_punto})
        facturado, unidades, anterior, anterior_mismo_punto, unidades_anterior = cursor.fetchone()
        cursor.execute("""
            SELECT fecha_venta, COALESCE(SUM(precio_venta * cantidad), 0) FROM ventas
            WHERE origen = 'meli' AND eliminado_en IS NULL AND fecha_venta BETWEEN %s AND %s GROUP BY fecha_venta
        """, (inicio_anterior, hoy))
        por_dia = {f: float(t) for f, t in cursor.fetchall()}
    facturado, anterior, anterior_mismo_punto = float(facturado), float(anterior), float(anterior_mismo_punto)
    if facturado <= 0 and anterior <= 0:
        return None
    proyectado = facturado / hoy.day * dias_mes if hoy.day >= MIN_DIAS_PROYECCION else None

    def variacion(a, b):
        return round((a - b) / b * 100, 1) if b > 0 else None
    return {
        "serie": serie_acumulada(por_dia, inicio, hoy, inicio_anterior, fin_anterior),
        "dia": hoy.day, "dias_mes": dias_mes, "avance_pct": round(hoy.day / dias_mes * 100),
        "facturado": formatear_moneda(facturado), "facturado_raw": round(facturado, 2), "unidades": int(unidades),
        "proyectado": formatear_moneda(proyectado) if proyectado is not None else None, "proyectado_raw": round(proyectado, 2) if proyectado is not None else None,
        "mes_anterior": formatear_moneda(anterior), "mes_anterior_raw": round(anterior, 2), "mismo_punto": formatear_moneda(anterior_mismo_punto),
        "vs_mismo_punto": variacion(facturado, anterior_mismo_punto), "vs_mes_anterior": variacion(proyectado, anterior) if proyectado is not None else None,
        "mes_nombre": MESES[hoy.month - 1], "mes_anterior_nombre": MESES[inicio_anterior.month - 1], "pocos_dias": hoy.day < MIN_DIAS_PROYECCION,
    }


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def armar_avisos(preguntas, reclamos, devoluciones, sin_stock):
    """
    Lo que la persona tiene que mirar ya, para la campana de la barra superior y los contadores del menú. Orden: lo que más urge primero.
    Cada aviso: clave, cantidad, texto (en castellano, con el número ya dicho), tono (danger/warn/info), href e icono.
    """
    def _mas(n, uno, varios):
        return uno if n == 1 else varios.format(n=n)

    candidatos = [
        ("reclamos", reclamos, _mas(reclamos, "1 reclamo que afecta tu reputación", "{n} reclamos que afectan tu reputación"), "danger", "/metricas#seccion-reclamos", "alert"),
        ("preguntas", preguntas, _mas(preguntas, "1 pregunta sin responder", "{n} preguntas sin responder"), "warn", "/dia#preguntas", "chat"),
        ("sin_stock", sin_stock, _mas(sin_stock, "1 publicación activa sin stock", "{n} publicaciones activas sin stock"), "warn", "/stock", "box"),
        ("devoluciones", devoluciones, _mas(devoluciones, "1 devolución por gestionar", "{n} devoluciones por gestionar"), "info", "/metricas#seccion-reclamos", "refresh"),
    ]
    items = [{"clave": c, "cantidad": int(n), "texto": t, "tono": tono, "href": href, "icono": icono} for c, n, t, tono, href, icono in candidatos if n and int(n) > 0]
    return {"total": sum(i["cantidad"] for i in items), "items": items}


def contar_preguntas_y_sin_stock(cursor):
    """(preguntas sin responder, publicaciones activas sin una sola unidad). Dos consultas livianas a la base; no llaman a Mercado Libre."""
    cursor.execute("SELECT COUNT(*) FROM preguntas_pendientes WHERE estado = 'pendiente'")
    preguntas = int(cursor.fetchone()[0] or 0)
    cursor.execute("""
        SELECT COUNT(*) FROM productos_padre p
        WHERE p.estado = 'active'
          AND COALESCE((SELECT SUM(COALESCE(v.stock_propio, 0) + COALESCE(v.stock_full, 0)) FROM productos_variantes v WHERE v.id_padre = p.id), 0) = 0
    """)
    return preguntas, int(cursor.fetchone()[0] or 0)


def obtener_ticker(usuario_id, cuenta_id=None):
    # Mismo criterio que obtener_ventas_hoy: "hoy" es el día en Argentina
    # (UTC-3), no el del reloj del sistema donde corra el proceso — si
    # alguna vez esto corre en un servidor en UTC en vez de en la PC del
    # usuario, datetime.now() a secas daría el día equivocado justo en las
    # horas cercanas a la medianoche.
    arg_now = datetime.now(ARGENTINA)
    hoy = arg_now.strftime("%Y-%m-%d")
    manana = (arg_now + timedelta(days=1)).strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0), COUNT(DISTINCT id_orden) FROM ventas WHERE fecha_venta = %s", (hoy,))
        fact_hoy, ord_hoy = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(monto_liberacion), 0) FROM ventas WHERE fecha_liberacion = %s", (manana,))
        liberacion_manana = cursor.fetchone()[0] or 0.0
        # Próxima acreditación y total que todavía falta acreditar (monto_liberacion = lo que MeLi deposita de verdad, ya sin comisiones ni envío)
        cursor.execute("""
            SELECT fecha_liberacion, SUM(monto_liberacion) FROM ventas WHERE fecha_liberacion >= %s AND monto_liberacion IS NOT NULL
            GROUP BY fecha_liberacion ORDER BY fecha_liberacion LIMIT 1
        """, (hoy,))
        fila_proxima = cursor.fetchone()
        proxima_liberacion = {"fecha": fila_proxima[0].strftime("%d/%m"), "monto": formatear_moneda(fila_proxima[1] or 0)} if fila_proxima else None
        cursor.execute("SELECT COALESCE(SUM(monto_liberacion), 0) FROM ventas WHERE fecha_liberacion >= %s", (hoy,))
        a_liberar_total = cursor.fetchone()[0] or 0.0

        cursor.execute("""
            SELECT titulo, cantidad, precio_venta, hora_venta FROM ventas
            WHERE fecha_venta = %s ORDER BY hora_venta DESC LIMIT 8
        """, (hoy,))
        ventas_hoy_detalle = []
        for t, c, p, h in cursor.fetchall():
            hora_str = h.strftime("%H:%M") if hasattr(h, "strftime") else (h or "")[:5]
            ventas_hoy_detalle.append({"titulo": t, "cantidad": c, "precio_formateado": formatear_moneda(p), "hora": hora_str})

        # Reclamos y devoluciones se cuentan POR SEPARADO (lo pidió el usuario: una devolución simple no es un
        # reclamo). Solo un reclamo real ('claim') puede afectar la reputación; una devolución es gestión del día a día.
        # Las cancelaciones no son nada que el vendedor tenga que resolver.
        # "Reclamo activo" = el que Mercado Libre dice que afecta la reputación (o que todavía no se sabe). Los que MeLi marca como
        # "no afecta" (p. ej. un "no lo quiero" en mediación) y las devoluciones van aparte, como gestión del día a día.
        cursor.execute(f"""
            SELECT COALESCE(SUM((tipo = 'claim' AND {SQL_RECLAMO_AFECTA})::int), 0),
                   COALESCE(SUM((tipo = 'return')::int), 0),
                   COALESCE(SUM((tipo = 'claim' AND NOT {SQL_RECLAMO_AFECTA})::int), 0)
            FROM incidencias_posventa WHERE estado NOT IN ('closed', 'resolved')
        """)
        incidencias_activas, devoluciones_activas, reclamos_sin_impacto = (int(x or 0) for x in cursor.fetchone())

        salud = salud_cuenta.calcular_score_salud(cursor)
        preguntas_sin_responder, publicaciones_sin_stock = contar_preguntas_y_sin_stock(cursor)

        # Ojo: si la migración de racha_dias todavía no corrió, esto
        # tira error — a propósito no hay try/except acá adentro: un
        # error de SQL deja la transacción en estado "aborted", y el
        # commit() del `with` de más arriba fallaría igual al salir, así
        # que atajarlo acá no evita nada, solo lo esconde peor.
        racha_dias = 0
        if cuenta_id:
            cursor.execute("SELECT racha_dias FROM cuentas_meli WHERE id = %s", (cuenta_id,))
            fila_racha = cursor.fetchone()
            racha_dias = (fila_racha[0] or 0) if fila_racha else 0

    return {
        "ventas_hoy": ord_hoy, "facturado_hoy": formatear_moneda(fact_hoy),
        "liberacion_manana": formatear_moneda(liberacion_manana), "proxima_liberacion": proxima_liberacion,
        "a_liberar_total": formatear_moneda(a_liberar_total), "hay_liberaciones": a_liberar_total > 0, "bridge_activo": False,
        "incidencias_activas": incidencias_activas, "devoluciones_activas": devoluciones_activas, "reclamos_sin_impacto": reclamos_sin_impacto, "salud_score": salud["score"], "racha_dias": racha_dias,
        "salud_etiqueta": salud["etiqueta"], "salud_detalle": salud["detalle"],
        "ventas_hoy_detalle": ventas_hoy_detalle,
        "avisos": armar_avisos(preguntas_sin_responder, incidencias_activas, devoluciones_activas, publicaciones_sin_stock),
    }


def obtener_tendencia_ventas(usuario_id, cuenta_id=None, dias=14):
    """
    Facturación por día de los últimos N días — para el gráfico de
    tendencia del Dashboard. Pedido explícito del usuario ("quiero
    gráficos, no solo cuadraditos"): esto no cambia el diseño general
    de la página (eso queda para una conversación de diseño aparte),
    solo agrega un widget más a la grilla existente, con el mismo
    patrón que los demás (una tarjeta que se arma con JS al cargar).
    """
    hoy_local = hoy_argentina()
    desde = hoy_local - timedelta(days=dias - 1)

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT fecha_venta, COALESCE(SUM(precio_venta * cantidad), 0)
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s
            GROUP BY fecha_venta
        """, (desde, hoy_local))
        por_fecha = {fila[0]: float(fila[1]) for fila in cursor.fetchall()}

    serie = []
    for i in range(dias):
        fecha = desde + timedelta(days=i)
        serie.append({"fecha": fecha.strftime("%d/%m"), "facturado": round(por_fecha.get(fecha, 0.0), 2)})

    total_periodo = sum(p["facturado"] for p in serie)
    return {
        "serie": serie, "total_formateado": formatear_moneda(total_periodo),
        "promedio_diario_formateado": formatear_moneda(total_periodo / dias if dias else 0),
    }


def obtener_quiebre_stock(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        return analisis_stock.obtener_variantes_en_riesgo(cursor)


def obtener_resumen_diario(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        return resumen_semanal.obtener_datos_resumen_diario(cursor)


def obtener_costos_resumen(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT titulo, precio, precio_costo, recibis_estimado FROM productos_padre
            WHERE estado = 'active' AND precio > 0 AND recibis_estimado IS NOT NULL
        """)
        filas = cursor.fetchall()

    margenes = []
    for titulo, precio, costo, recibis in filas:
        precio, costo, recibis = float(precio), float(costo or 0), float(recibis)
        comision = precio - recibis
        margen_pct = round(((precio - comision - costo) / precio) * 100, 1)
        margenes.append({"titulo": titulo, "margen_pct": margen_pct})

    if not margenes:
        return {"margen_promedio": None, "peor": None}

    margen_promedio = round(sum(m["margen_pct"] for m in margenes) / len(margenes), 1)
    peor = min(margenes, key=lambda m: m["margen_pct"])
    return {"margen_promedio": margen_promedio, "peor": peor}

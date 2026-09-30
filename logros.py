"""
Sistema de Logros/Misiones — portado de Santi Mens. La detección es
100% determinística; la redacción del mensaje "coach" la pule la IA
pero nunca es requisito (si falla, las misiones se ven igual).

Nota: la publicación "zombie" (que depende de embudo_conversion.py,
todavía no portado) queda afuera por ahora — se agrega cuando portemos
ese módulo, sin romper nada mientras tanto.
"""
import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
import analisis_stock
import embudo_conversion
import tendencias as tendencias_mod
import promociones as promociones_mod
import ia_asistente
import db

PRIORIDAD_ORDEN = {"urgente": 0, "importante": 1, "opcional": 2}


def _rollback_seguro(cursor):
    """
    Si un chequeo de misión falla (permiso faltante, tabla que no
    existe todavía, lo que sea), Postgres marca TODA la transacción
    como abortada — cualquier consulta siguiente en el mismo cursor
    falla también, aunque no tenga nada que ver, con
    "current transaction is aborted, commands ignored until end of
    transaction block". Encontrado en producción: eso tumbaba
    /api/dashboard/logro_top entero por un solo permiso faltante en
    una tabla que ni siquiera es la que el endpoint necesitaba. Este
    rollback deja la transacción lista de nuevo para que el resto de
    los chequeos (y el guardado del historial al final) sigan andando.
    """
    try:
        cursor.connection.rollback()
    except Exception:
        pass


def _detectar_misiones_base(cursor, cuenta_id):
    misiones = []

    try:
        en_riesgo = analisis_stock.obtener_variantes_en_riesgo(cursor)
        if en_riesgo:
            urgentes = [v for v in en_riesgo if v["dias_restantes"] <= 2]
            nivel = "urgente" if urgentes else "importante"
            misiones.append({
                "id": "stock_critico", "categoria": "stock", "icono": "📦", "prioridad": nivel,
                "titulo": f"{len(en_riesgo)} talle(s) por quedarse sin stock",
                "descripcion": f"Al ritmo de venta actual, {len(en_riesgo)} variante(s) se agotan pronto" + (f" — {len(urgentes)} en menos de 2 días." if urgentes else "."),
                "link": "/stock", "link_texto": "Ver en Stock"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando stock crítico: {e}")
        _rollback_seguro(cursor)

    try:
        curva_rota = analisis_stock.evaluar_curva_talles(cursor)
        if curva_rota:
            misiones.append({
                "id": "curva_rota", "categoria": "stock", "icono": "⚖️", "prioridad": "importante",
                "titulo": f"{len(curva_rota)} modelo(s) con la curva de talles rota",
                "descripcion": "Se están quedando sin los talles centrales (M/L/XL) mientras sobran los extremos — frena la venta del modelo entero.",
                "link": "/stock", "link_texto": "Ver modelos"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando curva rota: {e}")
        _rollback_seguro(cursor)

    try:
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(monto_retenido),0) FROM incidencias_posventa WHERE estado NOT IN ('closed','resolved') AND tipo != 'cancelacion'")
        cant_reclamos, monto_retenido = cursor.fetchone()
        if cant_reclamos > 0:
            monto_retenido_fmt = f"{float(monto_retenido):,.0f}".replace(",", ".")
            misiones.append({
                "id": "reclamos_abiertos", "categoria": "reclamos", "icono": "⚠️", "prioridad": "urgente" if cant_reclamos >= 3 else "importante",
                "titulo": f"{cant_reclamos} reclamo(s)/devolución(es) sin resolver",
                "descripcion": (f"Hay ${monto_retenido_fmt} retenidos esperando resolución — cada día que pasa sin responder puede sumar a tu reputación negativa." if monto_retenido else "Cada día que pasa sin responder puede sumar a tu reputación negativa."),
                "link": "/metricas", "link_texto": "Ver reclamos"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando reclamos abiertos: {e}")
        _rollback_seguro(cursor)

    try:
        cursor.execute("SELECT COUNT(*) FROM preguntas_pendientes WHERE estado = 'pendiente' AND creado_en < (now() - interval '1 day')")
        preguntas_viejas = cursor.fetchone()[0] or 0
        if preguntas_viejas > 0:
            misiones.append({
                "id": "preguntas_viejas", "categoria": "atencion", "icono": "❓", "prioridad": "importante",
                "titulo": f"{preguntas_viejas} pregunta(s) sin responder hace más de 24hs",
                "descripcion": "Una pregunta sin responder es una venta que se enfría.",
                "link": "/preguntas", "link_texto": "Responder preguntas"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando preguntas viejas: {e}")
        _rollback_seguro(cursor)

    try:
        canibalismo = tendencias_mod.detectar_canibalismo(cursor)
        if canibalismo:
            top = canibalismo[0]
            misiones.append({
                "id": "canibalismo", "categoria": "seo", "icono": "⚔️", "prioridad": "opcional",
                "titulo": f"{len(canibalismo)} par(es) de publicaciones compitiendo entre sí",
                "descripcion": f"'{top['modelo_a']}' y '{top['modelo_b']}' comparten {top['similitud_pct']}% de palabras — podrían estar dividiéndose las búsquedas.",
                "link": "/tendencias", "link_texto": "Ver detalle"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando canibalismo: {e}")
        _rollback_seguro(cursor)

    hoy = datetime.now().strftime("%Y-%m-%d")
    hace_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    hace_14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_7, hoy))
    semana_actual = float(cursor.fetchone()[0] or 0.0)
    cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_14, hace_7))
    semana_anterior = float(cursor.fetchone()[0] or 0.0)
    if semana_anterior > 0:
        variacion = ((semana_actual - semana_anterior) / semana_anterior) * 100
        if variacion <= -20:
            semana_actual_fmt = f"{semana_actual:,.0f}".replace(",", ".")
            semana_anterior_fmt = f"{semana_anterior:,.0f}".replace(",", ".")
            misiones.append({
                "id": "facturacion_cae", "categoria": "financiero", "icono": "📉", "prioridad": "urgente",
                "titulo": f"Facturación cayó {abs(round(variacion))}% esta semana",
                "descripcion": f"Pasaste de ${semana_anterior_fmt} a ${semana_actual_fmt} — vale la pena revisar precios, stock y publicidad de tus modelos top.",
                "link": "/metricas", "link_texto": "Ver Ganancia Real"
            })

    try:
        seo_scores = tendencias_mod.calcular_seo_scores_catalogo(cursor, [])
        muy_bajos = [s for s in seo_scores if s["score"] < 50]
        if muy_bajos:
            misiones.append({
                "id": "seo_bajo", "categoria": "seo", "icono": "📝", "prioridad": "opcional",
                "titulo": f"{len(muy_bajos)} título(s) con score de SEO bajo",
                "descripcion": f"'{muy_bajos[0]['titulo'][:40]}...' tiene {muy_bajos[0]['score']}/100 — hay margen real de mejora en cómo te encuentran.",
                "link": "/tendencias", "link_texto": "Ver Score de SEO"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error calculando SEO score: {e}")
        _rollback_seguro(cursor)

    try:
        movimiento = tendencias_mod.detectar_movimiento_categoria_principal(cursor, cuenta_id)
        if movimiento:
            direccion = "creció" if movimiento["subio"] else "se redujo"
            misiones.append({
                "id": "tendencia_categoria", "categoria": "tendencias", "icono": "📈" if movimiento["subio"] else "📉",
                "prioridad": "importante" if abs(movimiento["variacion_pct"]) >= 25 else "opcional",
                "titulo": f"La competencia en {movimiento['categoria']} {direccion} {abs(movimiento['variacion_pct'])}%",
                "descripcion": f"Cantidad de publicaciones activas, comparada con el relevamiento anterior — {'hay más vendedores peleando la misma vitrina: revisá precio y cómo te diferenciás' if movimiento['subio'] else 'hay menos oferta: puede ser buen momento para ganar visibilidad'}.",
                "link": "/tendencias", "link_texto": "Ver Tendencias"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error detectando movimiento de categoría: {e}")
        _rollback_seguro(cursor)

    try:
        impacto = promociones_mod.obtener_impacto_promociones(cursor)
        promos_sin_efecto = [i for i in impacto if i["activo"] and i["variacion_pct"] is not None and i["variacion_pct"] < 5]
        if promos_sin_efecto:
            p = promos_sin_efecto[0]
            misiones.append({
                "id": "promo_sin_efecto", "categoria": "financiero", "icono": "🏷️", "prioridad": "importante",
                "titulo": f"{len(promos_sin_efecto)} promoción(es) activa(s) sin impacto real",
                "descripcion": f"'{p['titulo']}' no aumentó significativamente el ritmo de venta desde que arrancó — estás regalando margen sin resultado a cambio.",
                "link": "/promociones", "link_texto": "Ver Promociones"
            })
    except Exception as e:
        print(f"[Logros] ⚠️ Error calculando impacto de promociones: {e}")
        _rollback_seguro(cursor)

    return misiones


def actualizar_historial_y_marcar_resueltas(cursor, cuenta_id, misiones_actuales):
    hoy = datetime.now().strftime("%Y-%m-%d")
    ids_actuales = {m["id"] for m in misiones_actuales}

    cursor.execute("SELECT mision_id FROM logros_historial WHERE cuenta_id = %s AND resuelta = false", (cuenta_id,))
    ids_previamente_activas = {r[0] for r in cursor.fetchall()}

    for m in misiones_actuales:
        cursor.execute("""
            INSERT INTO logros_historial (cuenta_id, mision_id, titulo, primera_vez_vista, ultima_vez_vista, resuelta)
            VALUES (%s, %s, %s, %s, %s, false)
            ON CONFLICT (cuenta_id, mision_id) DO UPDATE SET ultima_vez_vista = excluded.ultima_vez_vista, titulo = excluded.titulo, resuelta = false
        """, (cuenta_id, m["id"], m["titulo"], hoy, hoy))

    recien_resueltas = ids_previamente_activas - ids_actuales
    for mision_id in recien_resueltas:
        cursor.execute("UPDATE logros_historial SET resuelta = true, fecha_resuelta = %s WHERE cuenta_id = %s AND mision_id = %s", (hoy, cuenta_id, mision_id))

    return recien_resueltas


def obtener_logros_resueltos(cursor, cuenta_id, limite=10):
    cursor.execute("""
        SELECT titulo, fecha_resuelta FROM logros_historial
        WHERE cuenta_id = %s AND resuelta = true ORDER BY fecha_resuelta DESC LIMIT %s
    """, (cuenta_id, limite))
    resultado = []
    for titulo, fecha_resuelta in cursor.fetchall():
        fecha_fmt = fecha_resuelta.strftime("%Y-%m-%d") if hasattr(fecha_resuelta, "strftime") else fecha_resuelta
        resultado.append({"titulo": titulo, "fecha_resuelta": fecha_fmt})
    return resultado


def generar_mensaje_coach(misiones):
    if not misiones:
        return None
    resumen_misiones = "\n".join(f"- [{m['prioridad']}] {m['titulo']}" for m in misiones[:5])
    contexto = f"""
    Sos un coach de e-commerce para un vendedor de Mercado Libre. Estas son las misiones
    detectadas en su cuenta ahora mismo, ordenadas por prioridad:
    {resumen_misiones}

    Escribí un mensaje de 2-3 líneas, directo y motivador (no genérico, no digas "sigue así" sin más),
    que le diga CUÁL es la prioridad número uno a resolver hoy y por qué le conviene hacerlo ya.
    Español rioplatense. No inventes datos que no estén en la lista de arriba.
    """
    ok, resultado = ia_asistente.preguntar_ia(
        "Sos un coach de operaciones de e-commerce, directo y concreto.", contexto, max_tokens=200, temperatura=0.5
    )
    return resultado if ok else None


# El mensaje del coach es una llamada a la IA (segundos y plata). Antes se
# generaba en CADA carga de Logros y del Dashboard — hasta 9 s de espera por
# página. Ahora se cachea por cuenta: mientras las misiones prioritarias no
# cambien, se reutiliza el mismo mensaje (un caché por cuenta_id, no global:
# el texto habla de los datos de esa cuenta). Se calcula sobre las misiones de
# base de datos (sin las que consultan a MeLi) para que la página y el endpoint
# asíncrono lleguen a la misma firma.
_cache_coach = {}   # cuenta_id -> {"firma": str, "mensaje": str, "ts": float}
_LOCK_COACH = threading.Lock()
TTL_COACH_SEGUNDOS = 6 * 3600


def _top_misiones_coach(misiones_base):
    return sorted(misiones_base, key=lambda m: PRIORIDAD_ORDEN.get(m["prioridad"], 3))[:5]


def _firma_coach(top):
    return hashlib.sha1("|".join(f"{m['prioridad']}:{m['titulo']}" for m in top).encode("utf-8")).hexdigest()


def mensaje_coach_en_cache(cuenta_id, misiones_base):
    """El mensaje ya generado si sigue vigente para estas misiones, sin llamar a la IA."""
    top = _top_misiones_coach(misiones_base)
    if not top:
        return None
    with _LOCK_COACH:
        hit = _cache_coach.get(cuenta_id)
    if hit and hit["firma"] == _firma_coach(top) and time.time() - hit["ts"] < TTL_COACH_SEGUNDOS:
        return hit["mensaje"]
    return None


def generar_y_cachear_mensaje_coach(cuenta_id, misiones_base):
    top = _top_misiones_coach(misiones_base)
    if not top:
        return None
    cacheado = mensaje_coach_en_cache(cuenta_id, misiones_base)
    if cacheado:
        return cacheado
    mensaje = generar_mensaje_coach(top)
    if mensaje:
        with _LOCK_COACH:
            _cache_coach[cuenta_id] = {"firma": _firma_coach(top), "mensaje": mensaje, "ts": time.time()}
    return mensaje


def obtener_logros(cursor, cuenta_id, headers=None):
    misiones = _detectar_misiones_base(cursor, cuenta_id)
    misiones_base = list(misiones)

    if headers:
        try:
            zombies = embudo_conversion.detectar_publicaciones_zombie(headers, cuenta_id, cursor)
            if zombies:
                misiones.append({
                    "id": "zombies", "categoria": "seo", "icono": "💀", "prioridad": "opcional",
                    "titulo": f"{len(zombies)} publicación(es) sin visitas ni ventas en 60 días",
                    "descripcion": "Están activas pero no aportan nada — ocupan lugar en tu catálogo sin resultado.",
                    "link": "/embudo_conversion", "link_texto": "Ver detalle"
                })
        except Exception as e:
            print(f"[Logros] ⚠️ Error detectando zombies: {e}")
            _rollback_seguro(cursor)

    misiones.sort(key=lambda m: PRIORIDAD_ORDEN.get(m["prioridad"], 3))
    recien_resueltas = actualizar_historial_y_marcar_resueltas(cursor, cuenta_id, misiones)
    logros_resueltos = obtener_logros_resueltos(cursor, cuenta_id)

    if not misiones:
        return {
            "misiones": [], "mensaje_todo_bien": "🎉 No detectamos ningún problema pendiente en tu cuenta ahora mismo — lo estás haciendo bien. Volvé a revisar en unos días.",
            "mensaje_coach": None, "logros_resueltos": logros_resueltos, "recien_resueltas": len(recien_resueltas)
        }

    # Sin llamar a la IA acá: si hay un mensaje vigente se muestra al instante;
    # si no, la página lo pide aparte (/api/logros/coach) sin frenar la carga.
    mensaje_coach = mensaje_coach_en_cache(cuenta_id, misiones_base)
    return {
        "misiones": misiones, "mensaje_todo_bien": None, "mensaje_coach": mensaje_coach,
        "coach_pendiente": mensaje_coach is None and bool(misiones_base),
        "logros_resueltos": logros_resueltos, "recien_resueltas": len(recien_resueltas)
    }


def actualizar_racha(usuario_id, cuenta_id):
    """
    Racha de días activo (pedido explícito) — gamificación con memoria
    propia, no solo insignias por hito puntual. Se llama UNA vez por día
    (el propio caller, auth/middleware.py, usa un flag de sesión para no
    pegarle a la base en cada request — acá adentro no hay que
    preocuparse por eso).

    Requiere 2 columnas nuevas en cuentas_meli (ver migración pendiente
    junto con ventas.origen):
        ALTER TABLE cuentas_meli
            ADD COLUMN racha_dias INT NOT NULL DEFAULT 0,
            ADD COLUMN racha_ultimo_dia DATE;

    Devuelve la racha actualizada (días consecutivos, incluyendo hoy).
    """
    hoy_local = (datetime.now(timezone.utc) - timedelta(hours=3)).date()
    ayer_local = hoy_local - timedelta(days=1)

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT racha_dias, racha_ultimo_dia FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
        if not fila:
            return 0
        racha_dias, ultimo_dia = fila

        if ultimo_dia == hoy_local:
            return racha_dias or 0  # ya se contó hoy (no debería llegar hasta acá gracias al flag de sesión)
        elif ultimo_dia == ayer_local:
            racha_dias = (racha_dias or 0) + 1
        else:
            racha_dias = 1  # se cortó la racha (o es la primera vez)

        cursor.execute("UPDATE cuentas_meli SET racha_dias = %s, racha_ultimo_dia = %s WHERE id = %s", (racha_dias, hoy_local, cuenta_id))

    return racha_dias

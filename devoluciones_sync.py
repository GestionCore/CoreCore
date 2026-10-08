"""
Sincronizador de Reclamos/Devoluciones y Preguntas sin responder.

`incidencias_posventa` y `preguntas_pendientes` ya existían en el esquema
y varias páginas ya las leen para mostrar datos (Reclamos en Ganancia
Real, las misiones de Logros, el score de Salud de Cuenta) — pero hasta
ahora nada las llenaba desde la API real de MeLi, solo se habían probado
con filas cargadas a mano. Sin este módulo esas secciones quedan vacías
para siempre con una cuenta real, por más que ventas y catálogo sí
sincronicen bien.

Nota de confianza, para ser honesto sobre el riesgo de cada mitad:
- `sincronizar_preguntas` usa /questions/search, una de las APIs más
  viejas y estables de MeLi — bastante confianza en que esto funciona
  tal cual está.
- `sincronizar_reclamos` usa /post-purchase/v1/claims/search, que NO
  se pudo probar contra un token real en esta sesión (no había ninguno
  disponible). Si MeLi cambió la forma de la respuesta, esta parte va
  a fallar de forma RUIDOSA en la consola (no en silencio) para que se
  note enseguida — revisar la consola después del primer
  "Sincronizar Todo" que corra con este cambio, y ajustar acá si hace
  falta. El monto_retenido se completa aparte (_actualizar_dinero_retenido): es lo
  que Mercado Pago tiene retenido de verdad, o sea el pago de la orden en estado
  "in_mediation" mientras el reclamo sigue abierto.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import cache_db
import meli_http
import preguntas_sla
import db
import monitoreo

TAMANO_PAGINA = 50
LIMITE_OFFSET = 1000  # mismo tope de MeLi que ya mordimos con órdenes e ítems


def _mapear_tipo_claim(tipo_meli, stage):
    """
    Valores reales documentados por MeLi para el campo "type" de
    /post-purchase/v1/claims/search: "return" (devolución), "cancel_sale"
    (cancelación hecha por el vendedor) y "change" (cambio de producto/
    talle — muy común en indumentaria). Ninguno de estos tres afecta la
    reputación por sí solo; lo que sí la afecta es un reclamo real que
    entra en mediación. Antes "change" no estaba contemplado y caía en el
    default "claim" — por eso un simple cambio de talle aparecía en la
    UI mezclado con reclamos graves.
    """
    tipo_meli = (tipo_meli or "").lower()
    stage = (stage or "").lower()
    if "return" in tipo_meli or "devol" in tipo_meli:
        return "return"
    if "change" in tipo_meli or "cambio" in tipo_meli:
        return "return"
    if "cancel" in tipo_meli:
        return "cancelacion"
    return "claim"


def _mapear_estado_claim(status, stage):
    status = (status or "").lower()
    stage = (stage or "").lower()
    if status == "closed":
        return "closed"
    if stage in ("dispute", "mediation"):
        return "mediation"
    if stage == "claim" or status == "opened":
        return "claim"
    return status or "opened"


_MOTIVOS_ES = {
    # Códigos descriptivos
    "SHIPPING_DELAY": "Demora en el envío",
    "DAMAGE": "Artículo dañado",
    "NOT_AS_DESCRIBED": "Diferente a lo anunciado",
    "LOST": "Artículo perdido en tránsito",
    "SWITCH": "Artículo equivocado enviado",
    "ITEM_NOT_RECEIVED": "Artículo no recibido",
    "PRODUCT_DIFFERENT": "Producto diferente al anunciado",
    "DEFECT": "Artículo defectuoso",
    "INCOMPLETE": "Pedido incompleto",
    "DIFFERENT_COLOR": "Color diferente al publicado",
    "DIFFERENT_SIZE": "Talle diferente al publicado",
    "WRONG_ITEM": "Artículo equivocado",
    "MISSING_PARTS": "Partes o accesorios faltantes",
    "USED_AS_NEW": "Artículo usado vendido como nuevo",
    "COUNTERFEIT": "Artículo falsificado",
    "RETURN_REQUEST": "Solicitud de devolución",
    "CANCEL_REQUEST": "Solicitud de cancelación",
}


# Catálogo oficial de motivos de MeLi (PDD9939, PNR…): es el mismo para TODAS las cuentas, por eso
# puede cachearse a nivel de proceso sin mezclar datos entre cuentas.
_cache_motivos_oficiales = {}


def _motivo_oficial(headers, reason_id):
    """
    Texto real del motivo según Mercado Libre (GET /post-purchase/v1/claims/reasons/{id}).
    El mapeo a mano que había antes era inventado y estaba mal: PDD9939 es "Llegó lo que compré en
    buenas condiciones pero no lo quiero" (arrepentimiento), no "Artículo no recibido".
    """
    if not reason_id:
        return None
    if reason_id in _cache_motivos_oficiales:
        return _cache_motivos_oficiales[reason_id]
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/post-purchase/v1/claims/reasons/{reason_id}", headers=headers, timeout=10)
        if resp.status_code == 200:
            detalle = (resp.json().get("detail") or "").strip()
            if detalle:
                _cache_motivos_oficiales[reason_id] = detalle[:200]
                return _cache_motivos_oficiales[reason_id]
    except Exception as e:
        print(f"[DevolucionesSync] ⚠️ No se pudo consultar el motivo {reason_id}: {e}")
    return None   # los fallos no se cachean: se reintenta en la próxima sincronización


def _traducir_motivo(reason_id):
    """Respaldo cuando MeLi no devuelve el texto del motivo: nunca se inventa una explicación."""
    if not reason_id:
        return None
    traducido = _MOTIVOS_ES.get(reason_id)
    if traducido:
        return traducido
    if re.match(r"^[A-Za-z]{2,4}\d+$", reason_id):
        return f"Motivo {reason_id.upper()} (sin detalle de MeLi)"
    return reason_id.replace("_", " ").replace("-", " ").title()


def _parsear_fecha(fecha_raw):
    if not fecha_raw:
        return None
    try:
        return datetime.fromisoformat(fecha_raw.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return None


# Dos datos secundarios de cada reclamo abierto cambian muy de vez en cuando y se pedían a MeLi en CADA ciclo de 4 minutos (una llamada por reclamo abierto
# y otra por su orden): ahora se vuelven a pedir cada tanto. Un reclamo u orden que todavía no se consultó nunca se consulta en el acto.
VIGENCIA_IMPACTO_SEGUNDOS = 2 * 3600
VIGENCIA_RETENIDO_SEGUNDOS = 1 * 3600
CLAVE_IMPACTO, CLAVE_RETENIDO = "reclamos_impacto_consultado", "reclamos_retenido_consultado"


def filtrar_por_vigencia(ids, consultados, ahora, vigencia):
    """Los ids que hay que volver a consultar: los que nunca se consultaron o se consultaron hace `vigencia` segundos o más. `consultados` es {id: momento}."""
    return [i for i in ids if ahora - (consultados or {}).get(i, 0) >= vigencia]


def _sin_vencidos(consultados, ahora, maximo=24 * 3600):
    """La memoria de lo ya consultado no crece para siempre: se descarta lo de hace más de un día."""
    return {i: t for i, t in (consultados or {}).items() if ahora - t < maximo}


def sincronizar_reclamos(usuario_id, cuenta_id, access_token, seller_id):
    """Trae reclamos/mediaciones/devoluciones desde la API de post-venta de MeLi."""
    headers = {"Authorization": f"Bearer {access_token}"}
    offset = 0
    filas_totales = 0
    ids_abiertos = []
    lista_completa = False   # solo si se leyó TODA la lista de abiertos se puede cerrar lo que falta

    while True:
        try:
            resp = meli_http.get(
                "https://api.mercadolibre.com/post-purchase/v1/claims/search",
                headers=headers,
                params={"player.user_id": seller_id, "player.role": "respondent", "status": "opened", "offset": offset, "limit": TAMANO_PAGINA},
                timeout=15,
            )
        except Exception as e:
            print(f"[DevolucionesSync] ⚠️ Error de conexión trayendo reclamos: {e}")
            return filas_totales

        if resp.status_code != 200:
            print(f"[DevolucionesSync] ⚠️ /post-purchase/v1/claims/search devolvió {resp.status_code} — {resp.text[:300]} (¿cambió la forma de la API? revisar acá)")
            return filas_totales

        data = resp.json()
        claims = data.get("data") or data.get("results") or []
        if not claims:
            lista_completa = True
            break

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            # Siempre en el mismo orden (por id): dos sincronizaciones de la misma cuenta a la vez (el scheduler y un webhook) que escriben las mismas
            # filas en distinto orden terminaban en "deadlock detected".
            for c in sorted(claims, key=lambda c: str(c.get("id"))):
                id_reclamo = c.get("id")
                if id_reclamo is None:
                    continue
                id_reclamo = str(id_reclamo)
                ids_abiertos.append(id_reclamo)
                status = c.get("status")
                stage = c.get("stage")
                reason_id_crudo = c.get("reason_id") or (c.get("resolution", {}) or {}).get("reason")
                razon_oficial = _motivo_oficial(headers, reason_id_crudo)
                razon = razon_oficial or _traducir_motivo(reason_id_crudo)
                if reason_id_crudo and not razon_oficial and reason_id_crudo not in _MOTIVOS_ES:
                    # El mapeo de motivos (_MOTIVOS_ES) se armó sin poder
                    # probarlo contra reclamos reales — si esto aparece en
                    # producción, es la señal de que MeLi está devolviendo
                    # un reason_id que no contemplamos todavía. Logueamos
                    # el crudo para poder agregarlo al diccionario con el
                    # texto real, en vez de mostrar la traducción genérica
                    # (Title Case del código) sin verificar que sea correcta.
                    print(f"[DevolucionesSync] ⚠️ reason_id sin mapear en reclamo {id_reclamo}: '{reason_id_crudo}' (type={c.get('type')}, stage={stage}) — revisar y sumar a _MOTIVOS_ES")

                cursor.execute("""
                    INSERT INTO incidencias_posventa (cuenta_id, id_reclamo, id_orden, tipo, motivo, reason_id, estado, monto_retenido, fecha)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0.0, %s)
                    ON CONFLICT (cuenta_id, id_reclamo) DO UPDATE SET
                        estado = excluded.estado, motivo = COALESCE(excluded.motivo, incidencias_posventa.motivo),
                        reason_id = COALESCE(excluded.reason_id, incidencias_posventa.reason_id)
                """, (
                    cuenta_id, id_reclamo, str(c.get("resource_id") or ""),
                    _mapear_tipo_claim(c.get("type"), stage), razon, reason_id_crudo,
                    _mapear_estado_claim(status, stage), _parsear_fecha(c.get("date_created")),
                ))
                filas_totales += 1

        offset += TAMANO_PAGINA
        if len(claims) < TAMANO_PAGINA:
            lista_completa = True
            break
        if offset >= LIMITE_OFFSET:
            break

    # MeLi solo lista los reclamos ABIERTOS: los que se cerraron del lado de ellos dejaban de aparecer acá, pero en
    # nuestra base quedaban "abiertos" para siempre (se contaban 8 cuando MeLi tenía 6). Se cierran los que ya no vienen.
    if lista_completa:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                UPDATE incidencias_posventa SET estado = 'closed'
                WHERE cuenta_id = %s AND tipo IN ('claim', 'return', 'cancelacion') AND estado NOT IN ('closed', 'resolved')
                  AND NOT (id_reclamo = ANY(%s))
            """, (cuenta_id, ids_abiertos))
            if cursor.rowcount:
                print(f"[DevolucionesSync] Cuenta {cuenta_id}: {cursor.rowcount} reclamo(s)/devolución(es) ya cerrados en MeLi se cerraron acá también.")

    _actualizar_impacto_en_reputacion(usuario_id, cuenta_id, headers, ids_abiertos)
    _actualizar_dinero_retenido(usuario_id, cuenta_id, headers)
    _completar_motivos_viejos(usuario_id, cuenta_id, headers)
    return filas_totales


def _actualizar_dinero_retenido(usuario_id, cuenta_id, headers):
    """
    Plata que Mercado Pago tiene retenida por reclamos abiertos: el pago de la orden pasa a "in_mediation" y no se acredita hasta que se
    resuelve. Se suma el monto de esos pagos; si una orden tiene más de un reclamo se cuenta una sola vez. Los reclamos cerrados no retienen nada.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT id_reclamo, id_orden FROM incidencias_posventa
                WHERE cuenta_id = %s AND estado NOT IN ('closed', 'resolved') AND id_orden IS NOT NULL AND id_orden <> '' ORDER BY id_reclamo
            """, (cuenta_id,))
            abiertos = cursor.fetchall()
            cursor.execute("UPDATE incidencias_posventa SET monto_retenido = 0 WHERE cuenta_id = %s AND estado IN ('closed', 'resolved') AND monto_retenido <> 0", (cuenta_id,))
            _, consultadas = cache_db.leer(cursor, cuenta_id, CLAVE_RETENIDO, "v1", ttl_segundos=24 * 3600)
        if not abiertos:
            return
        ahora = time.time()
        consultadas = _sin_vencidos(consultadas if isinstance(consultadas, dict) else {}, ahora)

        def _retenido(id_orden):
            try:
                resp = meli_http.get(f"https://api.mercadolibre.com/orders/{id_orden}", headers=headers, timeout=10)
                if resp.status_code != 200:
                    return None
                return sum(float(p.get("transaction_amount") or 0) for p in (resp.json().get("payments") or []) if p.get("status") == "in_mediation")
            except Exception:
                return None

        ordenes = filtrar_por_vigencia(list(dict.fromkeys(o for _, o in abiertos)), consultadas, ahora, VIGENCIA_RETENIDO_SEGUNDOS)
        if not ordenes:
            return                 # todas se consultaron hace poco: el monto retenido guardado sigue vigente
        with ThreadPoolExecutor(max_workers=5) as pool:
            por_orden = dict(zip(ordenes, pool.map(_retenido, ordenes)))
        for orden, monto in por_orden.items():
            if monto is not None:
                consultadas[orden] = ahora
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cache_db.guardar(cursor, cuenta_id, CLAVE_RETENIDO, consultadas, "v1")
            ya_contadas = set()
            for id_reclamo, id_orden in abiertos:
                monto = por_orden.get(id_orden)
                if monto is None:
                    continue       # no se consultó ahora (o MeLi no respondió): se conserva lo que había
                monto_fila = 0.0 if id_orden in ya_contadas else monto
                ya_contadas.add(id_orden)
                cursor.execute("UPDATE incidencias_posventa SET monto_retenido = %s WHERE cuenta_id = %s AND id_reclamo = %s", (monto_fila, cuenta_id, id_reclamo))
    except Exception as e:
        print(f"[DevolucionesSync] ⚠️ No se pudo calcular el dinero retenido por reclamos: {e}")


def _impacto_en_reputacion(headers, id_reclamo):
    """GET /post-purchase/v1/claims/{id}/affects-reputation → "affected" | "not_affected" | otro valor de MeLi, o None si no respondió."""
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/post-purchase/v1/claims/{id_reclamo}/affects-reputation", headers=headers, timeout=10)
        if resp.status_code == 200:
            valor = (resp.json().get("affects_reputation") or "").strip().lower()
            return valor or None
    except Exception as e:
        print(f"[DevolucionesSync] ⚠️ No se pudo consultar el impacto en reputación del reclamo {id_reclamo}: {e}")
    return None


def _actualizar_impacto_en_reputacion(usuario_id, cuenta_id, headers, ids_abiertos, tope_viejos=15):
    """
    Si cada reclamo cuenta contra la reputación, según Mercado Libre. Los abiertos se vuelven a consultar siempre (puede cambiar
    mientras siguen abiertos); de los cerrados solo se completan los que nunca se consultaron, de a pocos por sincronización.
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_reclamo FROM incidencias_posventa
            WHERE cuenta_id = %s AND afecta_reputacion IS NULL AND NOT (id_reclamo = ANY(%s)) ORDER BY fecha DESC LIMIT %s
        """, (cuenta_id, ids_abiertos, tope_viejos))
        ids = list(ids_abiertos) + [r[0] for r in cursor.fetchall()]
        _, consultados = cache_db.leer(cursor, cuenta_id, CLAVE_IMPACTO, "v1", ttl_segundos=24 * 3600)
    ahora = time.time()
    consultados = _sin_vencidos(consultados if isinstance(consultados, dict) else {}, ahora)
    ids = filtrar_por_vigencia(ids, consultados, ahora, VIGENCIA_IMPACTO_SEGUNDOS)
    if not ids:
        return
    with ThreadPoolExecutor(max_workers=5) as pool:
        resultados = list(zip(ids, pool.map(lambda i: _impacto_en_reputacion(headers, i), ids)))
    for id_reclamo, valor in resultados:
        if valor:
            consultados[id_reclamo] = ahora
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cache_db.guardar(cursor, cuenta_id, CLAVE_IMPACTO, consultados, "v1")
        for id_reclamo, valor in sorted(resultados):          # en orden por id: ver el comentario de sincronizar_reclamos
            if valor:
                cursor.execute("UPDATE incidencias_posventa SET afecta_reputacion = %s WHERE cuenta_id = %s AND id_reclamo = %s", (valor, cuenta_id, id_reclamo))


def _completar_motivos_viejos(usuario_id, cuenta_id, headers, tope=15):
    """
    Reclamos guardados antes de tener `reason_id` (con el motivo traducido mal): se consulta cada uno a MeLi y se
    corrige con el texto oficial. Son pocos por pasada (`tope`), así una cuenta con mucho historial se va
    poniendo al día en las siguientes sincronizaciones sin frenar ésta.
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_reclamo FROM incidencias_posventa
            WHERE cuenta_id = %s AND reason_id IS NULL AND tipo IN ('claim', 'return', 'cancelacion') AND id_reclamo ~ '^[0-9]+$'
            ORDER BY fecha DESC NULLS LAST LIMIT %s
        """, (cuenta_id, tope))
        pendientes = [f[0] for f in cursor.fetchall()]
    for id_reclamo in pendientes:
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/post-purchase/v1/claims/{id_reclamo}", headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            reason_id = resp.json().get("reason_id")
        except Exception as e:
            print(f"[DevolucionesSync] ⚠️ No se pudo completar el reclamo {id_reclamo}: {e}")
            continue
        if not reason_id:
            continue
        texto = _motivo_oficial(headers, reason_id) or _traducir_motivo(reason_id)
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            conexion.cursor().execute(
                "UPDATE incidencias_posventa SET reason_id = %s, motivo = %s WHERE cuenta_id = %s AND id_reclamo = %s",
                (reason_id, texto, cuenta_id, id_reclamo)
            )


def sincronizar_preguntas(usuario_id, cuenta_id, access_token, seller_id):
    """
    Trae las preguntas sin responder desde MeLi. A diferencia de ventas
    (que es incremental), acá se pide SIEMPRE la lista completa de
    pendientes actuales — es la única forma de detectar que una pregunta
    que nosotros teníamos como 'pendiente' ya se respondió por otro lado
    (la app de MeLi, u otra herramienta) y hay que cerrarla acá también.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    offset = 0
    ids_sin_responder = set()

    while True:
        try:
            resp = meli_http.get(
                "https://api.mercadolibre.com/questions/search",
                headers=headers,
                params={"seller_id": seller_id, "status": "UNANSWERED", "limit": TAMANO_PAGINA, "offset": offset},
                timeout=15,
            )
        except Exception as e:
            print(f"[DevolucionesSync] ⚠️ Error de conexión trayendo preguntas: {e}")
            return len(ids_sin_responder)

        if resp.status_code != 200:
            print(f"[DevolucionesSync] ⚠️ /questions/search devolvió {resp.status_code} — {resp.text[:300]}")
            return len(ids_sin_responder)

        data = resp.json()
        preguntas = data.get("questions", [])
        if not preguntas:
            break

        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            for p in preguntas:
                qid = p.get("id")
                if qid is None:
                    continue
                qid = str(qid)
                ids_sin_responder.add(qid)
                # La hora de la pregunta es la que informa Mercado Libre (`date_created`); el límite es el objetivo interno de preguntas_sla (MeLi no informa un plazo)
                fecha_pregunta = preguntas_sla.fecha_de_meli(p.get("date_created"))
                cursor.execute("""
                    INSERT INTO preguntas_pendientes (cuenta_id, question_id, item_id, texto_pregunta, estado, fecha_pregunta, hora_limite_respuesta)
                    VALUES (%s, %s, %s, %s, 'pendiente', %s, %s)
                    ON CONFLICT (cuenta_id, question_id) DO UPDATE SET
                        texto_pregunta = excluded.texto_pregunta, estado = 'pendiente',
                        fecha_pregunta = excluded.fecha_pregunta, hora_limite_respuesta = excluded.hora_limite_respuesta
                """, (cuenta_id, qid, str(p.get("item_id") or ""), p.get("text"), fecha_pregunta, preguntas_sla.limite_de(fecha_pregunta)))

        offset += TAMANO_PAGINA
        total = data.get("total", 0)
        if offset >= total or offset >= LIMITE_OFFSET:
            break

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT question_id FROM preguntas_pendientes WHERE cuenta_id = %s AND estado = 'pendiente'", (cuenta_id,))
        pendientes_en_db = {fila[0] for fila in cursor.fetchall()}
        ids_a_cerrar = list(pendientes_en_db - ids_sin_responder)
        if ids_a_cerrar:
            cursor.execute(
                "UPDATE preguntas_pendientes SET estado = 'respondida' WHERE cuenta_id = %s AND question_id = ANY(%s)",
                (cuenta_id, ids_a_cerrar)
            )

    return len(ids_sin_responder)


def sincronizar_posventa(usuario_id, cuenta_id, access_token, seller_id):
    """
    Punto de entrada único que llama sincronizar_todo() — cada mitad va
    en su propio try/except para que un problema con reclamos (la parte
    menos probada) nunca tumbe la sincronización de preguntas, ni al
    revés.
    """
    try:
        n = sincronizar_reclamos(usuario_id, cuenta_id, access_token, seller_id)
        print(f"[DevolucionesSync] ✨ Cuenta {cuenta_id}: {n} reclamo(s)/devolución(es) sincronizados.")
    except Exception as e:
        print(f"❌ [DevolucionesSync] Error sincronizando reclamos de la cuenta {cuenta_id}: {e}")
        monitoreo.reportar("reclamos", e, cuenta_id)

    try:
        n = sincronizar_preguntas(usuario_id, cuenta_id, access_token, seller_id)
        print(f"[DevolucionesSync] ✨ Cuenta {cuenta_id}: {n} pregunta(s) sin responder.")
    except Exception as e:
        print(f"❌ [DevolucionesSync] Error sincronizando preguntas de la cuenta {cuenta_id}: {e}")
        monitoreo.reportar("preguntas", e, cuenta_id)

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
  falta. El monto_retenido queda en 0.0 a propósito: la lista de
  reclamos no lo trae, haría falta un pedido extra por reclamo a
  /post-purchase/v1/claims/{id} para tenerlo — queda pendiente como
  mejora futura, no algo que haya que inventar.
"""
from datetime import datetime
import meli_http
import db

TAMANO_PAGINA = 50
LIMITE_OFFSET = 1000  # mismo tope de MeLi que ya mordimos con órdenes e ítems


def _mapear_tipo_claim(tipo_meli, stage):
    tipo_meli = (tipo_meli or "").lower()
    stage = (stage or "").lower()
    if "return" in tipo_meli or "devol" in tipo_meli:
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
    # Códigos PDD (Post-venta / Defensa del Comprador)
    "PDD9939": "Artículo no recibido",
    "PDD9940": "Artículo dañado al llegar",
    "PDD9941": "Artículo diferente al anunciado",
    "PDD9942": "Artículo defectuoso",
    "PDD9943": "Pedido incompleto",
    "PDD9944": "Artículo equivocado enviado",
    "PDD9945": "Artículo perdido en tránsito",
    "PDD9946": "Calidad no corresponde",
    "PDD9947": "Talle/medida diferente al publicado",
    "PDD9948": "Color diferente al publicado",
}


def _traducir_motivo(reason_id):
    if not reason_id:
        return None
    traducido = _MOTIVOS_ES.get(reason_id)
    if traducido:
        return traducido
    # fallback: convertir código a texto legible
    return reason_id.replace("_", " ").replace("-", " ").title()


def _parsear_fecha(fecha_raw):
    if not fecha_raw:
        return None
    try:
        return datetime.fromisoformat(fecha_raw.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return None


def sincronizar_reclamos(usuario_id, cuenta_id, access_token, seller_id):
    """Trae reclamos/mediaciones/devoluciones desde la API de post-venta de MeLi."""
    headers = {"Authorization": f"Bearer {access_token}"}
    offset = 0
    filas_totales = 0

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
            break

        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            for c in claims:
                id_reclamo = c.get("id")
                if id_reclamo is None:
                    continue
                id_reclamo = str(id_reclamo)
                status = c.get("status")
                stage = c.get("stage")
                reason_id_crudo = c.get("reason_id") or (c.get("resolution", {}) or {}).get("reason")
                razon = _traducir_motivo(reason_id_crudo)
                if reason_id_crudo and reason_id_crudo not in _MOTIVOS_ES:
                    # El mapeo de motivos (_MOTIVOS_ES) se armó sin poder
                    # probarlo contra reclamos reales — si esto aparece en
                    # producción, es la señal de que MeLi está devolviendo
                    # un reason_id que no contemplamos todavía. Logueamos
                    # el crudo para poder agregarlo al diccionario con el
                    # texto real, en vez de mostrar la traducción genérica
                    # (Title Case del código) sin verificar que sea correcta.
                    print(f"[DevolucionesSync] ⚠️ reason_id sin mapear en reclamo {id_reclamo}: '{reason_id_crudo}' (type={c.get('type')}, stage={stage}) — revisar y sumar a _MOTIVOS_ES")

                cursor.execute("""
                    INSERT INTO incidencias_posventa (cuenta_id, id_reclamo, id_orden, tipo, motivo, estado, monto_retenido, fecha)
                    VALUES (%s, %s, %s, %s, %s, %s, 0.0, %s)
                    ON CONFLICT (cuenta_id, id_reclamo) DO UPDATE SET
                        estado = excluded.estado, motivo = COALESCE(excluded.motivo, incidencias_posventa.motivo)
                """, (
                    cuenta_id, id_reclamo, str(c.get("resource_id") or ""),
                    _mapear_tipo_claim(c.get("type"), stage), razon,
                    _mapear_estado_claim(status, stage), _parsear_fecha(c.get("date_created")),
                ))
                filas_totales += 1

        offset += TAMANO_PAGINA
        if offset >= LIMITE_OFFSET or len(claims) < TAMANO_PAGINA:
            break

    return filas_totales


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

        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            for p in preguntas:
                qid = p.get("id")
                if qid is None:
                    continue
                qid = str(qid)
                ids_sin_responder.add(qid)
                cursor.execute("""
                    INSERT INTO preguntas_pendientes (cuenta_id, question_id, item_id, texto_pregunta, estado)
                    VALUES (%s, %s, %s, %s, 'pendiente')
                    ON CONFLICT (cuenta_id, question_id) DO UPDATE SET
                        texto_pregunta = excluded.texto_pregunta, estado = 'pendiente'
                """, (cuenta_id, qid, str(p.get("item_id") or ""), p.get("text")))

        offset += TAMANO_PAGINA
        total = data.get("total", 0)
        if offset >= total or offset >= LIMITE_OFFSET:
            break

    with db.conexion_usuario(usuario_id) as conexion:
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

    try:
        n = sincronizar_preguntas(usuario_id, cuenta_id, access_token, seller_id)
        print(f"[DevolucionesSync] ✨ Cuenta {cuenta_id}: {n} pregunta(s) sin responder.")
    except Exception as e:
        print(f"❌ [DevolucionesSync] Error sincronizando preguntas de la cuenta {cuenta_id}: {e}")

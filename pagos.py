"""
Integración con Mercado Pago para suscripciones mensuales de CoreLux.

Usa la API de Preapproval (suscripciones recurrentes) de MP.
CoreLux necesita sus propias credenciales de MP en .env:
  MP_ACCESS_TOKEN=APP_USR-...
  (también MP_PUBLIC_KEY si se usa el SDK de frontend, pero el flujo
  de suscripciones usa solo el back_url redirect, así que no es crítico)

El flujo completo:
1. Usuario elige plan → llamamos crear_link_suscripcion → redirigimos a MP
2. Usuario autoriza en MP → MP redirige a /suscripcion/retorno con preapproval_id
3. MP manda webhook POST /webhook/mercadopago cuando la suscripción cambia de estado
4. Cada cobro mensual exitoso → MP actualiza el preapproval a "authorized"
5. Fallo de cobro / cancelación → MP lo pone en "cancelled" o "paused"
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import requests
import config

MP_BASE = "https://api.mercadopago.com"

PRECIOS_PLAN = {
    "base": 40000,
    "elite": 99000,
}

NOMBRES_PLAN = {
    "base": "CoreLux Plan Base — gestión completa para tu negocio en MeLi",
    "elite": "CoreLux Plan Elite — multi-cuenta, funciones avanzadas",
}

# Mapa de estados de MP → plan interno de CoreLux
# "authorized" = activo y al día  → plan activo
# "paused"     = cobro fallido, MP reintentará → igual contamos como activo por gracia
# "cancelled"  = cancelado definitivamente → bloquear
_ESTADO_MP_A_PLAN = {
    "authorized": "activo",
    "paused":     "activo",   # gracia: MP reintenta el cobro unos días
    "cancelled":  "cancelado",
    "pending":    "pending",  # usuario creó pero no pagó todavía
}


def _headers():
    return {
        "Authorization": f"Bearer {config.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def crear_link_suscripcion(plan, usuario_id, email, back_url):
    """
    Crea una suscripción recurrente mensual en MP.
    Devuelve (init_point_url, preapproval_id) o lanza excepción.
    """
    precio = PRECIOS_PLAN[plan]
    nombre = NOMBRES_PLAN[plan]
    payload = {
        "reason": nombre,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": precio,
            "currency_id": "ARS",
        },
        "payer_email": email,
        "back_url": back_url,
        "external_reference": f"{plan}|{usuario_id}",
        "status": "pending",
    }
    resp = requests.post(
        f"{MP_BASE}/preapproval",
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["init_point"], data["id"]


def obtener_estado_suscripcion(preapproval_id):
    """
    Consulta el estado actual de una suscripción en MP.
    Devuelve el dict completo de MP o None si falla.
    """
    resp = requests.get(
        f"{MP_BASE}/preapproval/{preapproval_id}",
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def cancelar_suscripcion(preapproval_id):
    """
    Cancela una suscripción activa en MP.
    Devuelve True si OK.
    """
    resp = requests.put(
        f"{MP_BASE}/preapproval/{preapproval_id}",
        json={"status": "cancelled"},
        headers=_headers(),
        timeout=10,
    )
    return resp.status_code == 200


def decidir_alta_o_cambio(plan_actual, mp_suscripcion_id, plan_pedido):
    """
    Qué hacer cuando alguien toca un plan en «Planes»:
      "cambiar"             → ya paga un plan por Mercado Pago y pide el de arriba (Base → Elite): se CAMBIA el monto de la suscripción que tiene, no se crea otra (se cobraría dos veces).
      "mismo"               → ya tiene ese plan.
      "bajar_no_disponible" → Elite → Base: hoy no se ofrece (un Elite puede tener más de una cuenta de Mercado Libre vinculada); se resuelve escribiendo.
      "a_mano"              → su plan lo dio el dueño a mano (cuentas de cortesía: sin suscripción de Mercado Pago): nunca se les arma un cobro por esta vía.
      "nueva"               → prueba o cancelado: se arma la suscripción nueva en Mercado Pago.
    """
    if plan_actual in ("base", "elite"):
        if not mp_suscripcion_id:
            return "a_mano"
        if plan_pedido == plan_actual:
            return "mismo"
        return "bajar_no_disponible" if plan_pedido == "base" else "cambiar"
    return "nueva"


def cambiar_plan_suscripcion(preapproval_id, plan, usuario_id):
    """
    Cambia el monto (y el nombre) de una suscripción YA existente al del plan nuevo, en vez de crear otra: así no se cobra dos veces. El nuevo monto rige desde el próximo cobro.
    Devuelve True solo si Mercado Pago lo aceptó Y la lectura posterior muestra el monto y la referencia nuevos (la referencia es de donde el webhook saca el plan: si quedara la vieja, el
    próximo aviso devolvería al usuario al plan anterior).
    """
    resp = requests.put(
        f"{MP_BASE}/preapproval/{preapproval_id}",
        json={
            "reason": NOMBRES_PLAN[plan],
            "auto_recurring": {"transaction_amount": PRECIOS_PLAN[plan], "currency_id": "ARS"},
            "external_reference": f"{plan}|{usuario_id}",
        },
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    info = obtener_estado_suscripcion(preapproval_id) or {}
    monto = (info.get("auto_recurring") or {}).get("transaction_amount")
    return monto is not None and float(monto) == float(PRECIOS_PLAN[plan]) and info.get("external_reference") == f"{plan}|{usuario_id}"


def firma_valida(x_signature, x_request_id, data_id, secreto):
    """
    Verifica la firma que Mercado Pago pone en cada webhook (cabecera x-signature = "ts=...,v1=<hmac>"): HMAC-SHA256, con el secreto de la
    integración, del texto "id:<data.id>;request-id:<x-request-id>;ts:<ts>;". Así solo se procesan avisos que realmente mandó Mercado Pago.
    Si no hay secreto configurado devuelve True (no se puede verificar): el webhook igual re-consulta el estado a la API de MP.
    """
    if not secreto:
        return True
    partes = dict(p.strip().split("=", 1) for p in (x_signature or "").split(",") if "=" in p)
    ts, recibida = partes.get("ts"), partes.get("v1")
    if not ts or not recibida:
        return False
    data_id = str(data_id or "")
    if data_id.isalnum():
        data_id = data_id.lower()                  # MP firma el id en minúsculas cuando es alfanumérico
    manifiesto = f"id:{data_id};request-id:{x_request_id or ''};ts:{ts};"
    esperada = hmac.new(secreto.encode(), manifiesto.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, recibida)


def diagnostico_firma(x_signature, x_request_id, data_id, secreto, ids_alternativos=None):
    """
    Texto para el log cuando una firma no coincide: dice QUÉ cabeceras llegaron y si la firma recibida coincide con alguna variante razonable del manifiesto
    (así se distingue "la clave es otra" de "el manifiesto se arma distinto"). Solo muestra los primeros 8 caracteres de cada HMAC: la clave no aparece ni se puede deducir.
    ids_alternativos = {nombre: id} de otros ids que traía el aviso (p. ej. el del cuerpo): se prueban con el manifiesto estándar por si Mercado Pago firma con otro.
    """
    partes = dict(p.strip().split("=", 1) for p in (x_signature or "").split(",") if "=" in p)
    ts, recibida = partes.get("ts"), (partes.get("v1") or "")
    data_id = str(data_id or "")
    id_firmado = data_id.lower() if data_id.isalnum() else data_id
    variantes = {
        "estandar": f"id:{id_firmado};request-id:{x_request_id or ''};ts:{ts};",
        "id_tal_cual": f"id:{data_id};request-id:{x_request_id or ''};ts:{ts};",
        "sin_request_id": f"id:{id_firmado};ts:{ts};",
        "sin_id": f"request-id:{x_request_id or ''};ts:{ts};",
        "sin_punto_y_coma_final": f"id:{id_firmado};request-id:{x_request_id or ''};ts:{ts}",
        "con_espacios": f"id:{id_firmado} request-id:{x_request_id or ''} ts:{ts}",
    }
    for nombre, otro in (ids_alternativos or {}).items():
        otro = str(otro or "")
        if otro and otro != data_id:
            variantes[nombre] = f"id:{otro.lower() if otro.isalnum() else otro};request-id:{x_request_id or ''};ts:{ts};"
    esperadas = {n: hmac.new((secreto or "").encode(), m.encode(), hashlib.sha256).hexdigest() for n, m in variantes.items()}
    coincide = [n for n, e in esperadas.items() if recibida and hmac.compare_digest(e, recibida)]
    resumen = ", ".join(f"{n}={e[:8]}" for n, e in esperadas.items())
    return (f"firma={'sí' if x_signature else 'no'} ts={'sí' if ts else 'no'} request_id={'sí' if x_request_id else 'no'} "
            f"v1_recibida={recibida[:8] or '-'} (largo {len(recibida)}) esperadas[{resumen}] coincide={','.join(coincide) or 'ninguna'}")


DIAS_DE_GRACIA_COBRO = 3     # decisión de Diego: si el cobro sale rechazado se sigue mirando 3 días (la tarjeta puede reintentarse y pasar); pasados sin cobro, el plan se da de baja


def _fecha_mp(valor):
    """Fecha ISO de Mercado Pago ('2026-11-07T20:25:37.000-04:00') → datetime con zona, o None si falta o no se entiende."""
    try:
        fecha = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def proximo_cobro(info):
    """Día del próximo cobro de una suscripción (el `next_payment_date` de MP) o None."""
    return _fecha_mp((info or {}).get("next_payment_date"))


def evaluar_renovacion(info, vencia_en, ahora):
    """
    Decide qué hacer el día de renovación de una suscripción, con lo que Mercado Pago informa hoy (`info` = GET /preapproval/{id}). Devuelve (accion, proximo_cobro, motivo):
      "cobrado"   → el cobro se acreditó (hay un cobro cerca de la fecha o después): se anota el próximo día de cobro y no se vuelve a mirar hasta entonces.
      "cancelada" → la suscripción está cancelada en Mercado Pago: el plan pasa a «cancelado».
      "sin_cobro" → pasaron más de DIAS_DE_GRACIA_COBRO días de la renovación sin cobro y la suscripción no está al día: se da de baja (y se cancela en MP para que no cobre a escondidas).
      "esperar"   → todavía no se puede saber (sin respuesta de MP, o dentro de los días de gracia): se vuelve a mirar en la próxima corrida.
    `vencia_en` es el día de cobro que teníamos anotado (None si todavía no se sabía).
    """
    if not info:
        return "esperar", vencia_en, "Mercado Pago no respondió"
    estado = info.get("status")
    if estado == "cancelled":
        return "cancelada", None, "la suscripción está cancelada en Mercado Pago"

    siguiente = proximo_cobro(info)
    ultimo_cobro = _fecha_mp((info.get("summarized") or {}).get("last_charged_date"))
    # Un día de margen: el cobro puede quedar acreditado unas horas antes o después de la hora anotada.
    cobrado = estado == "authorized" and ultimo_cobro is not None and (vencia_en is None or ultimo_cobro >= vencia_en - timedelta(days=1))
    if cobrado:
        return "cobrado", siguiente, "cobro acreditado"
    if vencia_en is None:
        return "esperar", siguiente, "todavía sin cobro registrado"
    if ahora - vencia_en > timedelta(days=DIAS_DE_GRACIA_COBRO):
        return "sin_cobro", None, f"sin cobro {DIAS_DE_GRACIA_COBRO} días después de la renovación (estado en Mercado Pago: {estado})"
    return "esperar", vencia_en, f"cobro pendiente (estado en Mercado Pago: {estado})"


def procesar_webhook(data, data_id_url=None, tipo_url=None):
    """
    Procesa un webhook de MP y devuelve (usuario_id, nuevo_plan, preapproval_id, proximo_cobro) o None.
    data = el JSON que mandó MP; data_id_url / tipo_url = los parámetros `data.id` y `type` de la URL (MP los manda ahí).
    Solo procesa topic="preapproval" — el de "payment" se ignora porque el
    estado del preapproval ya refleja si el cobro se acreditó o no.
    """
    topic = data.get("topic") or data.get("type") or tipo_url
    if topic not in ("preapproval", "subscription_preapproval"):
        return None

    # ⚠️ El id de la suscripción es `data.id`. El `id` de arriba del cuerpo es el número del AVISO (en el formato nuevo): usarlo consultaba otra cosa y nunca activaba el plan.
    # Solo en el formato viejo (IPN: topic + id) ese `id` de arriba es el recurso.
    preapproval_id = (
        data_id_url
        or (data.get("data") or {}).get("id")
        or (data.get("id") if data.get("topic") else None)
    )
    if not preapproval_id:
        return None

    preapproval_id = str(preapproval_id)
    info = obtener_estado_suscripcion(preapproval_id)
    if not info:
        return None

    status = info.get("status", "")
    external_ref = info.get("external_reference", "")

    # external_reference tiene formato "plan|usuario_id"
    if "|" not in external_ref:
        return None
    plan_str, uid_str = external_ref.split("|", 1)
    try:
        usuario_id = int(uid_str)
    except ValueError:
        return None

    estado_mp = _ESTADO_MP_A_PLAN.get(status)
    if not estado_mp:
        return None

    # Si autorizaron el pago, el plan queda como el plan elegido
    # Si cancelaron, queda "cancelado"
    if estado_mp == "activo":
        nuevo_plan = plan_str  # "base" o "elite"
    elif estado_mp == "cancelado":
        nuevo_plan = "cancelado"
    else:
        return None  # "pending" todavía no cambia nada

    return usuario_id, nuevo_plan, preapproval_id, proximo_cobro(info)

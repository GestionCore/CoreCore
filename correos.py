"""
Mails de CoreLux a las personas: solo avisos del servicio (cobro que no se pudo hacer, plan dado de baja o cambiado, fin de la prueba). No hay mails de marketing.

APAGADO por defecto: sin las tres variables `CORREO_PROVEEDOR`, `CORREO_API_KEY` y `CORREO_REMITENTE` (opcional `CORREO_RESPONDER_A`) no se manda nada ni se escribe nada en la base.
Para encenderlo hay que elegir un proveedor, verificar el dominio que manda (DNS en Cloudflare) y cargar las variables con `fly secrets set` (ver docs/RUNBOOK.md, «Mails»).
El único proveedor implementado es `resend` (API simple por HTTPS); para sumar otro basta una función en PROVEEDORES.

Reglas:
  · `avisar` NUNCA levanta una excepción: un mail que falla no puede romper un pago, una baja ni un webhook.
  · Cada aviso se reserva en `correos_enviados` ANTES de mandarlo (UNIQUE persona + tipo + clave) y se libera si el envío falla: no sale dos veces y se reintenta en la próxima corrida.
  · Nunca se manda a un email provisorio (`meli-<id>@pendiente.corelux.app`) ni a una dirección con saltos de línea (inyección de cabeceras).
  · Los textos hablan de lo que pasó y de lo que se puede hacer; no prometen lo que CoreLux no controla (los reintentos de cobro son de Mercado Pago).
"""
import html as _html
import logging
import os
from datetime import timedelta

import requests

import db
import pagos
from utils import fecha_corta, formatear_moneda

log = logging.getLogger("corelux.correos")

DOMINIO_PROVISORIO = "@pendiente.corelux.app"
TIPOS = ("cobro_pendiente", "plan_dado_de_baja", "plan_cambiado", "suscripcion_cancelada", "prueba_por_vencer", "prueba_vencida")
NOMBRES_PLAN = {"base": "Plan Base", "elite": "Plan Elite", "trial": "prueba gratuita"}


def _url_base():
    return (os.getenv("APP_URL") or "https://corelux.app").rstrip("/")


def configuracion():
    """{proveedor, api_key, remitente, responder_a} o None si falta algo (= mails apagados). Se lee del entorno en cada llamada."""
    proveedor = (os.getenv("CORREO_PROVEEDOR") or "").strip().lower()
    api_key = (os.getenv("CORREO_API_KEY") or "").strip()
    remitente = (os.getenv("CORREO_REMITENTE") or "").strip()
    if not (proveedor and api_key and remitente) or proveedor not in PROVEEDORES:
        return None
    return {"proveedor": proveedor, "api_key": api_key, "remitente": remitente, "responder_a": (os.getenv("CORREO_RESPONDER_A") or "").strip()}


def habilitado():
    return configuracion() is not None


# ── Proveedores ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _enviar_por_resend(cfg, destino, asunto, texto, cuerpo_html):
    """(ok, detalle). https://resend.com/docs/api-reference/emails/send-email"""
    datos = {"from": cfg["remitente"], "to": [destino], "subject": asunto, "text": texto}
    if cuerpo_html:
        datos["html"] = cuerpo_html
    if cfg.get("responder_a"):
        datos["reply_to"] = cfg["responder_a"]
    resp = requests.post("https://api.resend.com/emails", json=datos, headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=10)
    if 200 <= resp.status_code < 300:
        return True, "ok"
    return False, f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"


PROVEEDORES = {"resend": _enviar_por_resend}


def _destino_valido(destino):
    d = (destino or "").strip()
    return bool(d) and "@" in d and not any(c in d for c in "\r\n ,;<>") and not d.lower().endswith(DOMINIO_PROVISORIO)


def enviar(destino, asunto, texto, cuerpo_html=None):
    """'enviado' | 'apagado' | 'descartado' (destino inservible) | 'error'. No deja registro: para eso está `avisar`."""
    cfg = configuracion()
    if cfg is None:
        return "apagado"
    if not _destino_valido(destino) or any(c in (asunto or "") for c in "\r\n"):
        return "descartado"
    try:
        ok, detalle = PROVEEDORES[cfg["proveedor"]](cfg, destino.strip(), asunto, texto, cuerpo_html)
    except Exception as e:
        ok, detalle = False, f"{type(e).__name__}: {e}"
    if not ok:
        log.warning("[Correos] No se pudo enviar el mail (%s): %s", cfg["proveedor"], detalle)     # sin destino ni cuerpo: solo qué falló
        return "error"
    return "enviado"


# ── Textos ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _plata(valor):
    return f"${formatear_moneda(valor)}"


def _nombre_plan(plan):
    return NOMBRES_PLAN.get(plan, str(plan or "tu plan"))


def _precio_plan(plan):
    return pagos.PRECIOS_PLAN.get(plan)


def redactar(tipo, **d):
    """
    (asunto, [párrafos]) de cada aviso. Los datos que cambian el texto: plan, plan_anterior, plan_nuevo, proximo_cobro, limite (fecha hasta la que sigue activo),
    termina_en (fin de la prueba). Todo dato faltante se omite en vez de inventarse. None si el tipo no existe.
    """
    enlace = f"{_url_base()}/planes"
    if tipo == "cobro_pendiente":
        plan = d.get("plan")
        monto = _precio_plan(plan)
        p = [f"Intentamos renovar tu {_nombre_plan(plan)}" + (f" ({_plata(monto)} por mes)" if monto else "") + " y Mercado Pago todavía no acreditó el cobro."]
        if d.get("limite"):
            p.append(f"Tu plan sigue activo hasta el {fecha_corta(d['limite'])}. Si para esa fecha el cobro no se acreditó, lo damos de baja.")
        p.append("Revisá en Mercado Pago que el medio de pago tenga fondos y esté vigente; Mercado Pago puede volver a intentar el cobro por su cuenta.")
        p.append(f"Podés ver el estado de tu plan acá: {enlace}")
        return "No pudimos cobrar tu plan de CoreLux", p
    if tipo == "plan_dado_de_baja":
        plan = d.get("plan")
        p = [f"No se acreditó el cobro de tu {_nombre_plan(plan)} dentro de los {pagos.DIAS_DE_GRACIA_COBRO} días posteriores a la renovación, así que dimos de baja el plan y cancelamos la suscripción en Mercado Pago para que no se cobre más.",
             "Tus datos quedan guardados. Cuando quieras volver, te suscribís de nuevo y seguís donde dejaste.",
             f"Para volver a suscribirte: {enlace}"]
        return "Tu plan de CoreLux se dio de baja", p
    if tipo == "suscripcion_cancelada":
        plan = d.get("plan")
        p = [f"La suscripción a tu {_nombre_plan(plan)} está cancelada y no se van a hacer más cobros.",
             "Tus datos quedan guardados. Cuando quieras volver, te suscribís de nuevo y seguís donde dejaste.",
             f"Para volver a suscribirte: {enlace}"]
        return "Se canceló tu suscripción a CoreLux", p
    if tipo == "plan_cambiado":
        nuevo, anterior = d.get("plan_nuevo"), d.get("plan_anterior")
        monto = _precio_plan(nuevo)
        p = [f"Tu plan pasó de {_nombre_plan(anterior)} a {_nombre_plan(nuevo)}." if anterior else f"Tu plan ahora es {_nombre_plan(nuevo)}.",
             "No hicimos ningún cobro adicional por el cambio."
             + (" Desde tu próximo cobro" + (f" ({fecha_corta(d['proximo_cobro'])})" if d.get("proximo_cobro") else "") + f" pagás {_plata(monto)} por mes." if monto else ""),
             f"Podés ver el detalle de tu suscripción acá: {_url_base()}/suscripcion"]
        return f"Tu plan ahora es {_nombre_plan(nuevo)}", p
    if tipo == "prueba_por_vencer":
        fin = d.get("termina_en")
        p = [("Tu prueba gratuita de CoreLux termina el " + fecha_corta(fin) + ".") if fin else "Tu prueba gratuita de CoreLux está por terminar.",
             "Para seguir usando todo sin interrupciones, elegí un plan antes de esa fecha. Tus datos y tu configuración se mantienen.",
             f"Ver los planes: {enlace}"]
        return "Tu prueba gratuita de CoreLux está por terminar", p
    if tipo == "prueba_vencida":
        p = ["Tu prueba gratuita de CoreLux terminó.",
             "Tus datos y tu configuración quedan guardados: al elegir un plan seguís exactamente donde estabas.",
             f"Ver los planes: {enlace}"]
        return "Terminó tu prueba gratuita de CoreLux", p
    return None


def _a_html(parrafos):
    """HTML mínimo y sin imágenes: lo dinámico va escapado y los enlaces se arman a partir del texto ya escapado."""
    cuerpo = []
    for p in parrafos:
        seguro = _html.escape(p)
        for prefijo in ("https://", "http://"):
            if prefijo in seguro:
                inicio = seguro.index(prefijo)
                url = seguro[inicio:].split()[0]
                seguro = seguro[:inicio] + f'<a href="{url}">{url}</a>' + seguro[inicio + len(url):]
                break
        cuerpo.append(f'<p style="margin:0 0 14px;line-height:1.5">{seguro}</p>')
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:15px;color:#1f2330;max-width:520px">'
            + '<p style="margin:0 0 14px;line-height:1.5">Hola,</p>' + "".join(cuerpo)
            + '<p style="margin:18px 0 0;color:#6b7080;font-size:13px">CoreLux</p></div>')


def componer(tipo, **datos):
    """(asunto, texto, html) o None."""
    r = redactar(tipo, **datos)
    if r is None:
        return None
    asunto, parrafos = r
    texto = "Hola,\n\n" + "\n\n".join(parrafos) + "\n\nCoreLux\n"
    return asunto, texto, _a_html(parrafos)


# ── Avisar una sola vez ──────────────────────────────────────────────────────────────────────────────────────────────────────

def reservar(cursor, usuario_id, tipo, clave, destino):
    """True si el aviso se reservó (nadie lo mandó antes); False si ya existe."""
    cursor.execute(
        "INSERT INTO correos_enviados (usuario_id, tipo, clave, destino) VALUES (%s, %s, %s, %s) ON CONFLICT (usuario_id, tipo, clave) DO NOTHING RETURNING id",
        (usuario_id, tipo, str(clave or ""), destino),
    )
    return cursor.fetchone() is not None


def liberar(cursor, usuario_id, tipo, clave):
    cursor.execute("DELETE FROM correos_enviados WHERE usuario_id = %s AND tipo = %s AND clave = %s", (usuario_id, tipo, str(clave or "")))


def avisar(usuario_id, email, tipo, clave="", **datos):
    """
    Manda el aviso `tipo` una sola vez por (persona, tipo, clave). Devuelve 'enviado' | 'apagado' | 'ya_enviado' | 'descartado' | 'error' y nunca levanta una excepción.
    `clave` identifica el hecho que se avisa (el día de cobro, el id de la suscripción, la fecha de fin de la prueba): el mismo hecho no vuelve a mandarse; uno nuevo sí.
    """
    try:
        if not habilitado():
            return "apagado"
        if not _destino_valido(email):
            return "descartado"
        mail = componer(tipo, **datos)
        if mail is None:
            return "descartado"
        asunto, texto, cuerpo = mail
        with db.conexion_usuario(usuario_id) as conexion:
            reservado = reservar(conexion.cursor(), usuario_id, tipo, clave, email)
        if not reservado:
            return "ya_enviado"
        estado = enviar(email, asunto, texto, cuerpo)
        if estado != "enviado":
            with db.conexion_usuario(usuario_id) as conexion:
                liberar(conexion.cursor(), usuario_id, tipo, clave)          # se reintenta en la próxima corrida
        return estado
    except Exception as e:
        log.warning("[Correos] Falló el aviso %s del usuario %s: %s", tipo, usuario_id, e)
        return "error"


def fecha_de_corte(desde):
    """Último día en que sigue activo un plan cuyo cobro no se acreditó: el día de renovación + los días de gracia."""
    return desde + timedelta(days=pagos.DIAS_DE_GRACIA_COBRO) if desde else None

"""
Chequeo de renovaciones de las suscripciones de Mercado Pago.

No se pregunta todos los días si cada suscripción «sigue paga»: cada usuario guarda el día de su próximo cobro (`usuarios.mp_proximo_cobro`, el `next_payment_date` que informa
Mercado Pago) y la tarea diaria del scheduler consulta SOLO a quienes ya les llegó esa fecha. Si el cobro se acreditó, anota la fecha siguiente y no vuelve a mirar hasta entonces.
Si salió rechazado, se sigue mirando todos los días durante `pagos.DIAS_DE_GRACIA_COBRO` (3) y recién pasado ese plazo sin cobro se da de baja el plan (y se cancela en Mercado Pago, para
que no vuelva a cobrar a escondidas). Una suscripción cancelada en Mercado Pago pasa a «cancelado» enseguida.

Las cuentas de cortesía (Elite gratis a mano) no tienen `mp_suscripcion_id`: nunca entran acá. La decisión de qué hacer es `pagos.evaluar_renovacion` (función pura, probada aparte).
Es mantenimiento sin una persona detrás: usa la conexión de administración, como el webhook.
"""
from datetime import datetime, timedelta, timezone

import config
import correos
import db
import pagos

MARGEN_COBRO_PENDIENTE = timedelta(days=1)     # un cobro a las pocas horas de su hora no es «rechazado»: puede estar sin procesar. Recién al día siguiente se le avisa a la persona.
DIAS_AVISO_PRUEBA = 3                          # «tu prueba termina» se manda 3 días antes
DIAS_AVISO_PRUEBA_VENCIDA = 2                  # y «terminó» hasta 2 días después


def candidatos(cursor):
    """Usuarios con suscripción paga cuyo día de cobro ya llegó (o todavía no se anotó): [(usuario_id, plan, mp_suscripcion_id, mp_proximo_cobro)]."""
    cursor.execute("""
        SELECT id, plan, mp_suscripcion_id, mp_proximo_cobro
        FROM usuarios
        WHERE mp_suscripcion_id IS NOT NULL AND plan IN ('base', 'elite')
          AND (mp_proximo_cobro IS NULL OR mp_proximo_cobro <= now())
        ORDER BY id
    """)
    return cursor.fetchall()


def aplicar(cursor, usuario_id, accion, proximo):
    """Aplica la decisión sobre el usuario. «cancelada» y «sin_cobro» dan de baja el plan; «cobrado» y «esperar» solo anotan el día de cobro (si se conoce)."""
    if accion in ("cancelada", "sin_cobro"):
        # Solo a quien tiene suscripción de Mercado Pago: una cuenta de cortesía (Elite gratis a mano) no se da de baja por esta vía, pase lo que pase.
        cursor.execute("UPDATE usuarios SET plan = 'cancelado', mp_proximo_cobro = NULL WHERE id = %s AND plan IN ('base', 'elite') AND mp_suscripcion_id IS NOT NULL", (usuario_id,))
    elif proximo is not None:
        cursor.execute("UPDATE usuarios SET mp_proximo_cobro = %s WHERE id = %s AND mp_suscripcion_id IS NOT NULL", (proximo, usuario_id))


def avisos_de_renovacion(plan, mp_id, accion, vencia_en, ahora):
    """
    [(tipo de mail, clave, datos)] que corresponden a lo que se decidió con una suscripción (ver correos.py). Función pura.
    «cobro_pendiente» solo cuando ya pasó más de un día del día de cobro (antes puede ser un cobro sin procesar) y se manda una vez por ciclo de cobro (la clave es el día de cobro).
    """
    if accion == "sin_cobro":
        return [("plan_dado_de_baja", mp_id or "", {"plan": plan})]
    if accion == "cancelada":
        return [("suscripcion_cancelada", mp_id or "", {"plan": plan})]
    if accion == "esperar" and vencia_en is not None and ahora - vencia_en >= MARGEN_COBRO_PENDIENTE:
        return [("cobro_pendiente", vencia_en.date().isoformat(), {"plan": plan, "limite": correos.fecha_de_corte(vencia_en)})]
    return []


def _email_de(usuario_id):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT email FROM usuarios WHERE id = %s", (usuario_id,))
        fila = cursor.fetchone()
    return fila[0] if fila else None


def _mandar_avisos(avisar, usuario_id, avisos):
    """Manda los mails de una decisión. Con los mails apagados (y sin un `avisar` inyectado) no hace nada, ni siquiera busca el email. Nunca levanta una excepción."""
    if not avisos or (avisar is None and not correos.habilitado()):
        return
    try:
        email = _email_de(usuario_id)
        for tipo, clave, datos in avisos:
            (avisar or correos.avisar)(usuario_id, email, tipo, clave, **datos)
    except Exception as e:
        print(f"[Renovaciones] ⚠️ Usuario {usuario_id}: no se pudo mandar el aviso por mail ({e}).")


def avisar_pruebas(ahora=None, avisar=None):
    """
    Mails de la prueba gratuita: «termina el …» a quienes les faltan DIAS_AVISO_PRUEBA días o menos y «terminó» hasta DIAS_AVISO_PRUEBA_VENCIDA días después. La clave es la fecha de fin: si el
    administrador extiende la prueba, es otro aviso. Sin cobro habilitado (beta gratuita) la prueba no bloquea nada y no se manda nada; con los mails apagados tampoco. Devuelve {tipo: cantidad}.
    """
    resumen = {"prueba_por_vencer": 0, "prueba_vencida": 0}
    if not config.PAGOS_HABILITADOS or (avisar is None and not correos.habilitado()):
        return resumen
    ahora = ahora or datetime.now(timezone.utc)
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, email, trial_termina_en FROM usuarios WHERE plan = 'trial' AND activo AND trial_termina_en BETWEEN %s AND %s ORDER BY id",
            (ahora - timedelta(days=DIAS_AVISO_PRUEBA_VENCIDA), ahora + timedelta(days=DIAS_AVISO_PRUEBA)),
        )
        pruebas = cursor.fetchall()
    for usuario_id, email, termina_en in pruebas:
        tipo = "prueba_vencida" if termina_en < ahora else "prueba_por_vencer"
        try:
            (avisar or correos.avisar)(usuario_id, email, tipo, termina_en.date().isoformat(), termina_en=termina_en)
            resumen[tipo] += 1
        except Exception as e:
            print(f"[Renovaciones] ⚠️ Usuario {usuario_id}: no se pudo mandar el aviso de la prueba ({e}).")
    return resumen


def chequear_renovaciones(ahora=None, obtener=None, cancelar=None, avisar=None):
    """
    Revisa las suscripciones que vencen hoy o antes. `obtener`, `cancelar` y `avisar` se pueden reemplazar en las pruebas. Devuelve un resumen {accion: cantidad, "errores": n}.
    Un fallo con un usuario (Mercado Pago caído, respuesta rara) no corta a los demás ni cambia nada de ese usuario: se vuelve a intentar en la próxima corrida.
    Después de decidir, si hay mails configurados, avisa a la persona (cobro que no se pudo hacer, plan dado de baja, suscripción cancelada).
    """
    ahora = ahora or datetime.now(timezone.utc)
    obtener = obtener or pagos.obtener_estado_suscripcion
    cancelar = cancelar or pagos.cancelar_suscripcion
    resumen = {"cobrado": 0, "cancelada": 0, "sin_cobro": 0, "esperar": 0, "errores": 0}

    with db.conexion_admin() as conexion:
        pendientes = candidatos(conexion.cursor())

    for usuario_id, plan, mp_id, vencia_en in pendientes:
        try:
            info = obtener(mp_id)
            accion, proximo, motivo = pagos.evaluar_renovacion(info, vencia_en, ahora)
            if accion == "sin_cobro":
                try:
                    cancelar(mp_id)
                except Exception as e:     # el plan igual se da de baja: el aviso queda en el log para cancelarla a mano en Mercado Pago
                    print(f"[Renovaciones] ⚠️ Usuario {usuario_id}: no se pudo cancelar la suscripción {mp_id} en Mercado Pago ({e}).")
            with db.conexion_admin() as conexion:
                aplicar(conexion.cursor(), usuario_id, accion, proximo)
        except Exception as e:
            resumen["errores"] += 1
            print(f"[Renovaciones] ❌ Usuario {usuario_id}: {e}")
            continue
        _mandar_avisos(avisar, usuario_id, avisos_de_renovacion(plan, mp_id, accion, vencia_en, ahora))
        resumen[accion] += 1
        if accion != "esperar":
            print(f"[Renovaciones] Usuario {usuario_id} (plan {plan}): {accion} — {motivo}.")
    return resumen

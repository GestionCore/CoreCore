"""
Chequeo de renovaciones de las suscripciones de Mercado Pago.

No se pregunta todos los días si cada suscripción «sigue paga»: cada usuario guarda el día de su próximo cobro (`usuarios.mp_proximo_cobro`, el `next_payment_date` que informa
Mercado Pago) y la tarea diaria del scheduler consulta SOLO a quienes ya les llegó esa fecha. Si el cobro se acreditó, anota la fecha siguiente y no vuelve a mirar hasta entonces.
Si salió rechazado, se sigue mirando todos los días durante `pagos.DIAS_DE_GRACIA_COBRO` (3) y recién pasado ese plazo sin cobro se da de baja el plan (y se cancela en Mercado Pago, para
que no vuelva a cobrar a escondidas). Una suscripción cancelada en Mercado Pago pasa a «cancelado» enseguida.

Las cuentas de cortesía (Elite gratis a mano) no tienen `mp_suscripcion_id`: nunca entran acá. La decisión de qué hacer es `pagos.evaluar_renovacion` (función pura, probada aparte).
Es mantenimiento sin una persona detrás: usa la conexión de administración, como el webhook.
"""
from datetime import datetime, timezone

import db
import pagos


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


def chequear_renovaciones(ahora=None, obtener=None, cancelar=None):
    """
    Revisa las suscripciones que vencen hoy o antes. `obtener` y `cancelar` se pueden reemplazar en las pruebas. Devuelve un resumen {accion: cantidad, "errores": n}.
    Un fallo con un usuario (Mercado Pago caído, respuesta rara) no corta a los demás ni cambia nada de ese usuario: se vuelve a intentar en la próxima corrida.
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
        resumen[accion] += 1
        if accion != "esperar":
            print(f"[Renovaciones] Usuario {usuario_id} (plan {plan}): {accion} — {motivo}.")
    return resumen

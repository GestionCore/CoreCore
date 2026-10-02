"""
Tarea de salud del sistema — corre cada hora (definido en celery_app.py).

Responsabilidades:
  1. Verificar que los tokens de MeLi de cada cuenta activa sean renovables.
     Si un refresh falla dos veces seguidas, crea una alerta in-app para que
     el usuario sepa que tiene que reconectar su cuenta antes de que empiece
     a ver datos vacíos o errores 401.

  2. (Placeholder) En futuras fases: agregar más verificaciones de salud
     (estado del sync, quiebre de stock inminente, tasa de cancelación
     acercándose al límite, vencimiento de Monotributo, etc.).

La tabla `alertas_usuario` la crea la migración 0001 — tiene que estar
aplicada antes de que esta tarea empiece a correr.
"""
from celery_app import celery
import db
from auth import token_manager


def _obtener_cuentas_activas():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, usuario_id, nickname FROM cuentas_meli WHERE activa = true"
        )
        return cursor.fetchall()


def _crear_alerta(usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url=None):
    """
    Escribe una alerta in-app. Usa conexion_usuario (RLS activo) porque
    la política de alertas_usuario filtra por usuario_id, igual que el
    resto de las tablas personales.

    Para no spam: no crea una alerta duplicada si ya hay una no leída
    del mismo tipo para la misma cuenta.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            # Evitar duplicados: solo una alerta activa del mismo tipo por cuenta
            cursor.execute(
                """SELECT id FROM alertas_usuario
                   WHERE cuenta_id = %s AND tipo = %s AND leida = false""",
                (cuenta_id, tipo),
            )
            if cursor.fetchone():
                return  # Ya hay una alerta de este tipo pendiente de leer
            cursor.execute(
                """INSERT INTO alertas_usuario
                   (usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url),
            )
    except Exception as e:
        print(f"[Health] ⚠️ No se pudo crear la alerta (usuario={usuario_id}, tipo={tipo}): {e}")


@celery.task(name="tasks.health_tasks.tarea_verificar_tokens")
def tarea_verificar_tokens():
    """
    Verifica la salud del token de MeLi de cada cuenta activa.
    Si el refresh falla, crea una alerta visible para el usuario.
    """
    for cuenta_id, usuario_id, nickname in _obtener_cuentas_activas():
        try:
            # asegurar_token_valido intenta renovar si está cerca de vencer.
            # Si lanza CuentaDesconectada, el token ya no es recuperable.
            token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            nombre_cuenta = nickname or f"Cuenta #{cuenta_id}"
            _crear_alerta(
                usuario_id=usuario_id,
                cuenta_id=cuenta_id,
                tipo="token_vencido",
                titulo=f"Tu cuenta {nombre_cuenta} se desconectó",
                mensaje=(
                    "El acceso a Mercado Libre venció o fue revocado. "
                    "Reconectá tu cuenta para que CoreLux pueda seguir "
                    "sincronizando tus datos."
                ),
                accion_url="/reconectar",
            )
            print(f"[Health] ⚠️ Token vencido — cuenta {cuenta_id} ({nickname}). Alerta creada.")
        except Exception as e:
            # Error inesperado (red, base de datos) — loguear, no alertar al usuario
            print(f"[Health] ❌ Error verificando token de cuenta {cuenta_id}: {e}")

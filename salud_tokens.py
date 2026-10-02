"""
Verificación horaria de los permisos de Mercado Libre de cada cuenta activa.

Si el acceso se venció o fue revocado, `token_manager.asegurar_token_valido` lanza CuentaDesconectada: la sincronización de cada cuenta se
saltea en silencio y la persona se entera recién cuando vuelve a entrar (y la app la manda a reconectar). Esta tarea deja una alerta in-app
(`alertas_usuario`, sin duplicarla mientras siga sin leerse) para que el aviso exista aunque nadie esté mirando la pantalla; cuando haya
notificaciones por mail, es el punto de donde sale el aviso.

Antes vivía en tasks/health_tasks.py, que solo corría con Celery (que existe únicamente en la PC del dueño): en producción nunca se ejecutó.
"""
import db
from auth import token_manager


def _cuentas_activas():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, usuario_id, nickname FROM cuentas_meli WHERE activa = true")
        return cursor.fetchall()


def crear_alerta(usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url=None):
    """
    Escribe una alerta in-app con RLS activo (la política de alertas_usuario filtra por usuario_id). No crea una duplicada si ya hay una sin leer
    del mismo tipo para la misma cuenta.
    """
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT id FROM alertas_usuario WHERE cuenta_id = %s AND tipo = %s AND leida = false", (cuenta_id, tipo))
            if cursor.fetchone():
                return False
            cursor.execute(
                "INSERT INTO alertas_usuario (usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url) VALUES (%s, %s, %s, %s, %s, %s)",
                (usuario_id, cuenta_id, tipo, titulo, mensaje, accion_url),
            )
            return True
    except Exception as e:
        print(f"[Salud] ⚠️ No se pudo crear la alerta (usuario={usuario_id}, tipo={tipo}): {e}")
        return False


def verificar_tokens():
    """Recorre las cuentas activas; las que ya no se pueden renovar dejan una alerta. Devuelve cuántas cuentas desconectadas encontró."""
    desconectadas = 0
    for cuenta_id, usuario_id, nickname in _cuentas_activas():
        try:
            token_manager.asegurar_token_valido(cuenta_id)       # renueva si está por vencer; lanza si ya no es recuperable
        except token_manager.CuentaDesconectada:
            desconectadas += 1
            crear_alerta(
                usuario_id, cuenta_id, "token_vencido", f"Tu cuenta {nickname or f'#{cuenta_id}'} se desconectó",
                "El acceso a Mercado Libre venció o fue revocado. Reconectá tu cuenta para que CoreLux pueda seguir sincronizando tus datos.",
                accion_url="/reconectar",
            )
            print(f"[Salud] ⚠️ Permiso vencido: cuenta {cuenta_id} ({nickname}).")
        except Exception as e:
            print(f"[Salud] ❌ No se pudo verificar la cuenta {cuenta_id}: {e}")      # red o base caídas: no es motivo de alertar a la persona
    return desconectadas

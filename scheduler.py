"""
Scheduler de CoreLux.

En producción (con Redis disponible):
  Las tareas periódicas las maneja Celery Beat — correr en proceso separado:
      celery -A celery_app beat --loglevel=info
  Este módulo detecta que Redis está disponible e imprime un mensaje
  informativo. iniciar_scheduler() es un no-op en ese caso.

En desarrollo (sin Redis):
  Fallback automático a APScheduler corriendo en un hilo de fondo del mismo
  proceso de Flask. No es ideal (muere si Flask se reinicia, no escala a
  múltiples workers) pero suficiente para testear localmente sin instalar Redis.

El API externo (iniciar_scheduler()) no cambia — app.py lo llama igual.
"""
from apscheduler.schedulers.background import BackgroundScheduler
import config
import db
import sincronizador
import espia_competencia
import motor_combos
import tendencias as tendencias_mod
from auth import token_manager

_scheduler_apscheduler = None


def _redis_disponible():
    try:
        import redis
        r = redis.from_url(config.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


def _obtener_cuentas_activas():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE activa = true")
        return cursor.fetchall()


def _tarea_sincronizar_todo():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            sincronizador.sincronizar_todo(usuario_id, cuenta_id)
        except Exception as e:
            print(f"[Scheduler APScheduler] ❌ Error cuenta {cuenta_id}: {e}")


def _tarea_relevar_competencia():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                relevados = espia_competencia.relevar_competidores(cursor)
                if relevados:
                    print(f"[Scheduler APScheduler] 🔍 Cuenta {cuenta_id}: {relevados} rival(es) relevado(s).")
        except Exception as e:
            print(f"[Scheduler APScheduler] ❌ Error competencia cuenta {cuenta_id}: {e}")


def _tarea_relevar_tendencias():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            access_token = token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            continue
        except Exception as e:
            print(f"[Scheduler APScheduler] ⚠️ No se pudo refrescar el token de la cuenta {cuenta_id} para tendencias: {e}")
            continue
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                relevados = tendencias_mod.relevar_snapshots_tendencias(access_token, cursor, cuenta_id)
                if relevados:
                    print(f"[Scheduler APScheduler] 📊 Cuenta {cuenta_id}: {relevados} snapshot(s) de tendencias tomados.")
        except Exception as e:
            print(f"[Scheduler APScheduler] ❌ Error tendencias cuenta {cuenta_id}: {e}")


def _tarea_analizar_combos():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                motor_combos.analizar_combos(cursor, cuenta_id)
        except Exception as e:
            print(f"[Scheduler APScheduler] ❌ Error combos cuenta {cuenta_id}: {e}")


def iniciar_scheduler():
    """
    Punto de entrada llamado desde app.py en el bloque __main__.
    Si Redis está disponible, asume que Celery Beat corre por separado.
    Si no, arranca APScheduler como fallback.
    """
    global _scheduler_apscheduler

    if _redis_disponible():
        print(
            "[Scheduler] ✅ Redis detectado — tareas periódicas delegadas a Celery Beat.\n"
            "            Correr en proceso separado:\n"
            "            celery -A celery_app beat --loglevel=info"
        )
        return

    # Fallback a APScheduler
    if _scheduler_apscheduler is not None:
        return

    print(
        "[Scheduler] ⚠️  Redis no disponible — usando APScheduler como fallback.\n"
        "            Las tareas periódicas corren en este mismo proceso de Flask.\n"
        "            Para producción: instalá Redis y corré Celery Beat por separado."
    )

    _scheduler_apscheduler = BackgroundScheduler(daemon=True)
    _scheduler_apscheduler.add_job(_tarea_sincronizar_todo, "interval", minutes=4, id="sync_todo")
    _scheduler_apscheduler.add_job(_tarea_relevar_competencia, "interval", hours=24, id="relevar")
    _scheduler_apscheduler.add_job(_tarea_relevar_tendencias, "interval", hours=24, id="relevar_tendencias")
    _scheduler_apscheduler.add_job(_tarea_analizar_combos, "interval", days=7, id="combos")
    _scheduler_apscheduler.start()
    print("[Scheduler] ✅ APScheduler iniciado (sync cada 4 min, para todas las cuentas).")

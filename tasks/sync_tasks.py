"""
Tareas de sincronización — reemplazan las tareas de APScheduler en
scheduler.py y los threading.Thread(daemon=True) de app.py.

Diferencias clave vs. el código anterior:
  - Si el worker de Celery se cae a mitad de una tarea, la tarea se
    reencola y se vuelve a intentar (task_acks_late=True en celery_app.py).
    Con daemon threads eso no era posible: si Flask se reiniciaba con un
    sync en vuelo, ese sync se perdía para siempre.
  - Las tareas periódicas (beat) se controlan desde un proceso separado,
    sin ocupar un thread del pool de Flask.
  - `bind=True` + `self.retry()` dan backoff exponencial automático ante
    fallas transitorias (rate limit de MeLi, timeout de red, etc.).

Compatibilidad hacia atrás: scheduler.py detecta si Celery/Redis está
disponible. Si no, arranca APScheduler como fallback — así la app
funciona en dev local sin Redis instalado.
"""
from celery_app import celery
import db
import sincronizador
import espia_competencia
import motor_combos
import tendencias as tendencias_mod
from auth import token_manager


def _obtener_cuentas_activas():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, usuario_id FROM cuentas_meli WHERE activa = true"
        )
        return cursor.fetchall()


@celery.task(
    bind=True,
    name="tasks.sync_tasks.sincronizar_todo_task",
    max_retries=2,
    default_retry_delay=60,
)
def sincronizar_todo_task(self, usuario_id, cuenta_id):
    """
    Sync inicial disparado desde /callback cuando el usuario conecta su
    cuenta. Reemplaza threading.Thread(daemon=True) en app.py.
    """
    try:
        sincronizador.sincronizar_todo(usuario_id, cuenta_id)
    except Exception as exc:
        print(f"[Celery] ❌ sincronizar_todo_task: cuenta {cuenta_id}: {exc}")
        raise self.retry(exc=exc)


@celery.task(name="tasks.sync_tasks.tarea_sincronizar_todo")
def tarea_sincronizar_todo():
    """Sync periódico de TODAS las cuentas activas — corre cada 4 minutos."""
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            sincronizador.sincronizar_todo(usuario_id, cuenta_id)
        except Exception as e:
            print(f"[Celery Beat] ❌ Error sincronizando la cuenta {cuenta_id}: {e}")


@celery.task(name="tasks.sync_tasks.tarea_relevar_competencia")
def tarea_relevar_competencia():
    """Relevamiento de competidores — corre cada 24 horas."""
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            access_token = token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            continue
        try:
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                cursor = conexion.cursor()
                relevados = espia_competencia.relevar_competidores(cursor, cuenta_id, access_token)
                if relevados:
                    print(f"[Celery Beat] 🔍 Cuenta {cuenta_id}: {relevados} competidor(es) relevado(s).")
        except Exception as e:
            print(f"[Celery Beat] ❌ Error relevando competencia de la cuenta {cuenta_id}: {e}")


@celery.task(name="tasks.sync_tasks.tarea_relevar_tendencias")
def tarea_relevar_tendencias():
    """Snapshot diario de las tendencias seguidas (categorías/términos) — corre cada 24 horas."""
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            access_token = token_manager.asegurar_token_valido(cuenta_id)
        except token_manager.CuentaDesconectada:
            continue
        except Exception as e:
            print(f"[Celery Beat] ⚠️ No se pudo refrescar el token de la cuenta {cuenta_id} para tendencias: {e}")
            continue
        try:
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                cursor = conexion.cursor()
                relevados = tendencias_mod.relevar_snapshots_tendencias(access_token, cursor, cuenta_id)
                if relevados:
                    print(f"[Celery Beat] 📊 Cuenta {cuenta_id}: {relevados} snapshot(s) de tendencias tomados.")
        except Exception as e:
            print(f"[Celery Beat] ❌ Error relevando tendencias de la cuenta {cuenta_id}: {e}")


@celery.task(name="tasks.sync_tasks.tarea_analizar_combos")
def tarea_analizar_combos():
    """Análisis de combos de productos — corre cada 7 días."""
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                cursor = conexion.cursor()
                motor_combos.analizar_combos(cursor, cuenta_id)
        except Exception as e:
            print(f"[Celery Beat] ❌ Error analizando combos de la cuenta {cuenta_id}: {e}")

"""
Tareas periódicas — portado de Santi Mens. Cambio real: el original
corría cada tarea UNA VEZ, para la única cuenta que existía. Acá cada
tarea recorre TODAS las cuentas activas (`cuentas_meli.activa = true`),
una por una, con su propio try/except — así una cuenta con problemas
(token vencido, cuenta desconectada) no frena la sincronización de las
demás.

Deliberadamente no incluye todavía: la auditoría de devoluciones/
cancelaciones (depende de portar devoluciones_sync.py y ventas_sync.py)
ni las alertas por WhatsApp de stock/curva de talles (sin puente
todavía) — quedan para cuando se porten esos módulos.
"""
from apscheduler.schedulers.background import BackgroundScheduler
import db
import sincronizador
import espia_competencia
import motor_combos
from auth import token_manager

_scheduler = None


def _obtener_cuentas_activas():
    """Lee directo con el pool admin porque esto corre en segundo plano,
    sin un usuario autenticado en sesión del que colgar app.usuario_actual."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE activa = true")
        return cursor.fetchall()


def _tarea_sincronizar_catalogos():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            sincronizador.sincronizar_todo(usuario_id, cuenta_id)
        except Exception as e:
            print(f"[Scheduler] ❌ Error sincronizando la cuenta {cuenta_id}: {e}")


def _tarea_relevar_competencia():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                relevados = espia_competencia.relevar_competidores(cursor)
                if relevados:
                    print(f"[Scheduler] 🔍 Cuenta {cuenta_id}: {relevados} competidor(es) relevado(s).")
        except Exception as e:
            print(f"[Scheduler] ❌ Error relevando competencia de la cuenta {cuenta_id}: {e}")


def _tarea_analizar_combos():
    for cuenta_id, usuario_id in _obtener_cuentas_activas():
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                motor_combos.analizar_combos(cursor, cuenta_id)
        except Exception as e:
            print(f"[Scheduler] ❌ Error analizando combos de la cuenta {cuenta_id}: {e}")


def _envoltorio_seguro(funcion, nombre):
    def envoltura():
        try:
            funcion()
        except Exception as e:
            print(f"[Scheduler] ❌ Error en tarea '{nombre}': {e}")
    return envoltura


def iniciar_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_envoltorio_seguro(_tarea_sincronizar_catalogos, "sincronizar_catalogos"), "interval", minutes=4, id="sincronizar_catalogos")
    _scheduler.add_job(_envoltorio_seguro(_tarea_relevar_competencia, "relevar_competencia"), "interval", hours=24, id="relevar_competencia")
    _scheduler.add_job(_envoltorio_seguro(_tarea_analizar_combos, "analizar_combos"), "interval", days=7, id="analizar_combos")
    _scheduler.start()
    print("[Scheduler] ✅ Tareas periódicas iniciadas (sincronización cada 4 min, para todas las cuentas activas).")

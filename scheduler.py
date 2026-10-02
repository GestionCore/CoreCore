"""
Scheduler de CoreLux: las tareas periódicas corren con APScheduler dentro del proceso web, y un lock de Postgres hace que de todos los workers
y máquinas UNO solo las ejecute (el resto vigila por si ese cae). Es el mismo camino en producción y en la PC: antes, con Redis (solo en la PC del
dueño) las tareas se delegaban a Celery y el sistema se portaba distinto que en producción.

  · cada 4 minutos: sincronización de todas las cuentas activas
  · cada hora: verificación de los permisos de Mercado Libre (salud_tokens)
  · cada 24 horas: relevamiento de competencia y de tendencias
"""
from apscheduler.schedulers.background import BackgroundScheduler
import db
import salud_tokens
import sincronizador
import espia_competencia
import tendencias as tendencias_mod
from auth import token_manager

_scheduler_apscheduler = None
_conexion_lock_scheduler = None  # se mantiene abierta a propósito, ver _tiene_el_lock_del_scheduler

# Número arbitrario para el advisory lock de Postgres — cualquier bigint
# sirve, con tal de no chocar con otro lock nombrado en el resto de la
# app (no hay ningún otro pg_advisory_lock en el código a la fecha).
ID_LOCK_SCHEDULER = 727270001


def _tiene_el_lock_del_scheduler():
    """
    Con gunicorn corriendo más de un worker (ej. --workers 2 en Railway),
    cada worker importa app.py por separado y, sin esto, cada uno arrancaría
    su PROPIO APScheduler — la sincronización de cada cuenta correría 2
    (o N) veces en simultáneo cada 4 minutos, multiplicando exactamente la
    carga que hace lenta a la app en vez de repartirla.

    pg_try_advisory_lock es un lock de sesión: dura mientras la conexión
    siga abierta. Por eso esta conexión NO se devuelve al pool ni se
    cierra — se mantiene viva a propósito durante toda la vida del proceso
    del worker que ganó el lock, para retenerlo. Si Postgres no está
    disponible en este instante (arranque en frío, etc.), se falla "abierto"
    (devuelve True) — preferible correr el scheduler de más una vez a que
    no corra en ninguna, que dejaría de sincronizar cuentas en silencio.
    """
    global _conexion_lock_scheduler
    try:
        conexion = db.obtener_conexion_admin()
        cursor = conexion.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (ID_LOCK_SCHEDULER,))
        obtuvo_lock = cursor.fetchone()[0]
        conexion.commit()
        if obtuvo_lock:
            _conexion_lock_scheduler = conexion  # se retiene, no se libera
            return True
        db.liberar_conexion_admin(conexion)
        return False
    except Exception as e:
        print(f"[Scheduler] ⚠️ No se pudo chequear el advisory lock ({e}) — arranca igual, por las dudas.")
        return True


def _obtener_cuentas_activas():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE activa = true")
        return cursor.fetchall()


SYNC_CUENTAS_EN_PARALELO = 2     # con el tope de conexiones de la base (db.POOL_MAX) no conviene más


def _sincronizar_una(par):
    cuenta_id, usuario_id = par
    try:
        sincronizador.sincronizar_todo(usuario_id, cuenta_id)
    except Exception as e:
        print(f"[Scheduler APScheduler] ❌ Error cuenta {cuenta_id}: {e}")


def _tarea_sincronizar_todo():
    """Sincroniza todas las cuentas activas, de a SYNC_CUENTAS_EN_PARALELO a la vez (en serie, con muchas cuentas el ciclo de 4 min no alcanzaba)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=SYNC_CUENTAS_EN_PARALELO) as pool:
        list(pool.map(_sincronizar_una, _obtener_cuentas_activas()))


def _tarea_relevar_competencia():
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
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                cursor = conexion.cursor()
                relevados = tendencias_mod.relevar_snapshots_tendencias(access_token, cursor, cuenta_id)
                if relevados:
                    print(f"[Scheduler APScheduler] 📊 Cuenta {cuenta_id}: {relevados} snapshot(s) de tendencias tomados.")
        except Exception as e:
            print(f"[Scheduler APScheduler] ❌ Error tendencias cuenta {cuenta_id}: {e}")


def _tarea_verificar_tokens():
    salud_tokens.verificar_tokens()


def iniciar_scheduler():
    """
    Punto de entrada llamado desde app.py al importarse (una vez por proceso). Solo un proceso tiene el lock y corre las tareas; los demás
    quedan vigilando por si ese se cae.
    """
    global _scheduler_apscheduler

    if _scheduler_apscheduler is not None:
        return

    if not _tiene_el_lock_del_scheduler():
        print("[Scheduler] ℹ️  Otro worker ya tiene el scheduler — este queda vigilando por si ese cae.")
        import threading
        threading.Thread(target=_vigilar_el_lock, daemon=True, name="vigilante-scheduler").start()
        return

    _arrancar_apscheduler()


def _vigilar_el_lock(cada_segundos=60):
    """
    Si el worker que tiene el scheduler se cae, su conexión se cierra y el lock se libera, pero los demás ya habían decidido "lo tiene otro"
    al arrancar y no volvían a mirar: la sincronización se frenaba hasta el próximo reinicio. Este hilo reintenta cada minuto.
    """
    import time
    while _scheduler_apscheduler is None:
        time.sleep(cada_segundos)
        try:
            if _tiene_el_lock_del_scheduler():
                print("[Scheduler] ♻️  El scheduler anterior ya no está: este worker lo toma.")
                _arrancar_apscheduler()
                return
        except Exception as e:
            print(f"[Scheduler] ⚠️ Vigilante: {e}")


def _arrancar_apscheduler():
    global _scheduler_apscheduler
    if _scheduler_apscheduler is not None:
        return
    _scheduler_apscheduler = BackgroundScheduler(daemon=True)
    _scheduler_apscheduler.add_job(_tarea_sincronizar_todo, "interval", minutes=4, id="sync_todo", max_instances=1, coalesce=True)
    _scheduler_apscheduler.add_job(_tarea_relevar_competencia, "interval", hours=24, id="relevar")
    _scheduler_apscheduler.add_job(_tarea_relevar_tendencias, "interval", hours=24, id="relevar_tendencias")
    _scheduler_apscheduler.add_job(_tarea_verificar_tokens, "interval", hours=1, id="verificar_tokens", max_instances=1, coalesce=True)
    _scheduler_apscheduler.start()
    print("[Scheduler] ✅ APScheduler iniciado (sync cada 4 min, para todas las cuentas).")

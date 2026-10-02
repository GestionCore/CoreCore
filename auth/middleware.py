"""
Middleware de autenticación — decorador para proteger rutas y helper
para saber qué usuario/cuenta está atendiendo cada request.
"""
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import session, redirect, url_for, g, request, render_template, abort
from auth import registro
import db
import config
import nav_config

# Rutas que tienen que funcionar SIEMPRE, aunque la primera sincronización
# todavía no haya terminado — si no las excluimos acá, el usuario queda
# atrapado en la pantalla de espera sin poder cerrar sesión, reconectar,
# ni que el propio JS de esa pantalla consulte si ya terminó.
_PERMITIDAS_DURANTE_SINCRONIZACION = {
    "logout", "reconectar", "conectar", "callback", "landing",
    "api_estado_sincronizacion", "sincronizar_manual", "onboarding_vista", "onboarding_guardar", "onboarding_tutorial_visto",
    "legal.cuenta_eliminar",
}
_PERMITIDAS_DURANTE_ONBOARDING = {"logout", "reconectar", "conectar", "callback", "onboarding_vista", "onboarding_guardar", "legal.cuenta_eliminar"}
_PERMITIDAS_SIN_SUSCRIPCION = {
    "logout", "landing", "planes_vista", "suscripcion_iniciar", "suscripcion_retorno",
    "suscripcion_vista", "suscripcion_cancelar", "webhook_mercadopago", "admin_panel",
    "admin_usuarios", "admin_cambiar_plan", "salud_sistema.admin_salud", "legal.cuenta_eliminar",
}


def login_requerido(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        usuario_id = session.get("usuario_id")
        cuenta_id = session.get("cuenta_id")
        if not usuario_id or not cuenta_id:
            return redirect(url_for("landing"))
        g.usuario_id = usuario_id
        g.cuenta_id = cuenta_id

        necesita_onboarding = request.endpoint not in _PERMITIDAS_DURANTE_ONBOARDING
        necesita_sync = request.endpoint not in _PERMITIDAS_DURANTE_SINCRONIZACION
        necesita_plan = request.endpoint not in _PERMITIDAS_SIN_SUSCRIPCION

        # Los 3 chequeos de arriba antes abrían su propia conexión y hacían
        # su propio viaje de ida y vuelta a Postgres, en serie — 3 round
        # trips (contra el pooler de SESIÓN de Supabase, más lento que uno
        # de transacción) en CADA carga de página, antes de que la ruta
        # ni siquiera arrancara a traer sus propios datos. Para la mayoría
        # de las páginas (todos los 3 chequeos aplican) se combinan acá en
        # una sola consulta/conexión — mismos datos, mismo criterio de
        # redirect, un solo viaje en vez de tres.
        if necesita_onboarding or necesita_sync or necesita_plan:
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("""
                    SELECT u.onboarding_completo, u.plan, u.trial_termina_en, cm.sincronizacion_inicial_completa
                    FROM usuarios u
                    LEFT JOIN cuentas_meli cm ON cm.id = %s
                    WHERE u.id = %s
                """, (cuenta_id, usuario_id))
                fila = cursor.fetchone()

            if fila:
                onboarding_completo, plan_actual, trial_termina_en, sync_completa = fila

                if necesita_onboarding and not onboarding_completo:
                    return redirect(url_for("onboarding_vista"))

                if necesita_sync and sync_completa is not None and not sync_completa:
                    return render_template("sincronizando.html")

                if necesita_plan:
                    if plan_actual == "cancelado":
                        return redirect(url_for("planes_vista"))
                    if plan_actual == "trial" and trial_termina_en:
                        if datetime.now(timezone.utc) > trial_termina_en:
                            return redirect(url_for("planes_vista"))

        # Racha de días activo: un flag de sesión evita pegarle a la base
        # en cada request — solo se actualiza la primera vez que se entra
        # en el día (hora Argentina), no en cada click. Mismo criterio
        # UTC-3 que usa actualizar_racha, para que coincidan.
        hoy_local = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")
        if session.get("racha_actualizada_el") != hoy_local:
            try:
                import logros
                logros.actualizar_racha(usuario_id, cuenta_id)
            except Exception as e:
                print(f"[Middleware] ⚠️ Error actualizando racha: {e}")
            session["racha_actualizada_el"] = hoy_local

        # "MÁS USADO": igual que la racha, se recalcula una sola vez por
        # día (no en cada click) y se guarda en sesión — el menú y el
        # tab-strip lo leen de ahí sin pegarle a la base en cada render.
        if session.get("mas_usado_actualizado_el") != hoy_local:
            try:
                session["mas_usado"] = _calcular_mas_usado_sesion(usuario_id)
            except Exception as e:
                print(f"[Middleware] ⚠️ Error calculando más usado: {e}")
            session["mas_usado_actualizado_el"] = hoy_local

        return vista(*args, **kwargs)
    return envoltorio


def _calcular_mas_usado_sesion(usuario_id):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT nav_key, contador FROM navegacion_visitas WHERE usuario_id = %s", (usuario_id,))
        filas = cursor.fetchall()
    contadores = {nav_key: contador for nav_key, contador in filas}
    return nav_config.calcular_mas_usado(contadores)


def admin_requerido(vista):
    """
    Decorador que verifica que el usuario logueado sea el administrador
    de CoreLux. Debe ir dentro de @login_requerido (que ya setea g.usuario_id).
    Usa ADMIN_EMAIL del .env — si está vacío, siempre deniega.
    """
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if not config.ADMIN_EMAIL:
            abort(403)
        with db.conexion_usuario(g.usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT email FROM usuarios WHERE id = %s", (g.usuario_id,))
            fila = cursor.fetchone()
        if not fila or fila[0].lower() != config.ADMIN_EMAIL.lower():
            abort(403)
        return vista(*args, **kwargs)
    return envoltorio


def iniciar_sesion(usuario_id, cuenta_id):
    session.permanent = True      # vence a los 14 días (PERMANENT_SESSION_LIFETIME, ver seguridad.py)
    session["usuario_id"] = usuario_id
    session["cuenta_id"] = cuenta_id


def cerrar_sesion():
    session.clear()


def cambiar_cuenta_activa(cuenta_id):
    """Para cuando un usuario con varias cuentas (plan Elite) cambia cuál está viendo."""
    cuentas_del_usuario = registro.obtener_cuentas_de_usuario(session["usuario_id"])
    if any(c["id"] == cuenta_id for c in cuentas_del_usuario):
        session["cuenta_id"] = cuenta_id
        return True
    return False

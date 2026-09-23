"""
Middleware de autenticación — decorador para proteger rutas y helper
para saber qué usuario/cuenta está atendiendo cada request.
"""
from functools import wraps
from flask import session, redirect, url_for, g, request, render_template
from auth import registro
import db

# Rutas que tienen que funcionar SIEMPRE, aunque la primera sincronización
# todavía no haya terminado — si no las excluimos acá, el usuario queda
# atrapado en la pantalla de espera sin poder cerrar sesión, reconectar,
# ni que el propio JS de esa pantalla consulte si ya terminó.
_PERMITIDAS_DURANTE_SINCRONIZACION = {
    "logout", "reconectar", "conectar", "callback", "landing",
    "api_estado_sincronizacion", "sincronizar_todo", "onboarding_vista", "onboarding_guardar", "onboarding_tutorial_visto",
}
_PERMITIDAS_DURANTE_ONBOARDING = {"logout", "reconectar", "conectar", "callback", "onboarding_vista", "onboarding_guardar"}


def login_requerido(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        usuario_id = session.get("usuario_id")
        cuenta_id = session.get("cuenta_id")
        if not usuario_id or not cuenta_id:
            return redirect(url_for("landing"))
        g.usuario_id = usuario_id
        g.cuenta_id = cuenta_id

        if request.endpoint not in _PERMITIDAS_DURANTE_ONBOARDING:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("SELECT onboarding_completo FROM usuarios WHERE id = %s", (usuario_id,))
                fila_onb = cursor.fetchone()
            if fila_onb and not fila_onb[0]:
                return redirect(url_for("onboarding_vista"))

        if request.endpoint not in _PERMITIDAS_DURANTE_SINCRONIZACION:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("SELECT sincronizacion_inicial_completa FROM cuentas_meli WHERE id = %s", (cuenta_id,))
                fila = cursor.fetchone()
            if fila and not fila[0]:
                return render_template("sincronizando.html")

        return vista(*args, **kwargs)
    return envoltorio


def iniciar_sesion(usuario_id, cuenta_id):
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

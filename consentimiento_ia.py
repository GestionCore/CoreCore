"""
Consentimiento para las funciones con IA (migración 0052, `usuarios.ia_consentimiento_en`).

Mandar texto de la cuenta a un proveedor externo de IA es "divulgar a terceros" (cláusula 2.1.f de los Términos de la API de Mercado Libre): solo se hace si la persona lo
aceptó. Sin aceptar, las cinco rutas que llaman a la IA contestan 403 con un texto que lleva a Mi cuenta (cada pantalla lo muestra con su propio mecanismo) y el resto de CoreLux
funciona igual. El control está en el servidor: esconder un botón no alcanza.
"""
from functools import wraps

from flask import g, jsonify

import db

MENSAJE_SIN_CONSENTIMIENTO = ("Las funciones con IA están desactivadas en tu cuenta. Para usarlas, activalas en Mi cuenta: "
                              "ahí ves qué datos se envían al servicio externo de IA y podés cambiarlo cuando quieras.")


def tiene(usuario_id):
    """¿Aceptó usar las funciones con IA? Ante cualquier falla (también si la migración todavía no corrió) la respuesta es no: lo seguro es no enviar nada."""
    try:
        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT ia_consentimiento_en IS NOT NULL FROM usuarios WHERE id = %s", (usuario_id,))
            fila = cursor.fetchone()
        return bool(fila and fila[0])
    except Exception as e:
        print(f"[ConsentimientoIA] ⚠️ No se pudo leer el consentimiento del usuario {usuario_id}: {type(e).__name__}")
        return False


def guardar(usuario_id, acepta):
    """Acepta (fecha de hoy) o retira (NULL) el consentimiento. Devuelve False si no se pudo guardar."""
    try:
        with db.conexion_usuario(usuario_id) as conexion:
            conexion.cursor().execute(
                "UPDATE usuarios SET ia_consentimiento_en = CASE WHEN %s THEN now() ELSE NULL END WHERE id = %s", (bool(acepta), usuario_id))
        return True
    except Exception as e:
        print(f"[ConsentimientoIA] ⚠️ No se pudo guardar el consentimiento del usuario {usuario_id}: {type(e).__name__}")
        return False


def respuesta_bloqueada():
    """
    El 403 que reciben las pantallas con IA. Lleva el mismo texto bajo todas las claves que esas pantallas leen (cada una tiene su forma de mostrar un error)
    y un botón que lleva a Mi cuenta, que el chat dibuja tal cual.
    """
    mensaje = MENSAJE_SIN_CONSENTIMIENTO
    return jsonify({"ok": False, "sin_consentimiento_ia": True, "error": mensaje, "detalle": mensaje, "mensaje": mensaje, "respuesta": mensaje, "accion": "error",
                    "botones": [{"texto": "Activar la IA en Mi cuenta", "url": "/cuenta#ia"}]}), 403


def requerido(vista):
    """Decorador para las rutas que llaman a la IA. Va DEBAJO de @login_requerido (necesita g.usuario_id)."""
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if not tiene(g.usuario_id):
            return respuesta_bloqueada()
        return vista(*args, **kwargs)
    return envoltorio

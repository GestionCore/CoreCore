"""
Páginas legales (Términos y Privacidad) y la baja de la cuenta con borrado de todos los datos.

Es el primer Blueprint de la app: de a poco se va sacando de app.py lo que tiene sentido por sí solo.
"""
import os
from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, g
import config
import db
import pagos
from auth.middleware import login_requerido, cerrar_sesion

bp = Blueprint("legal", __name__)

CONTACTO_EMAIL = os.getenv("CONTACTO_EMAIL", "soporte@corelux.app")
ULTIMA_ACTUALIZACION = "1 de octubre de 2026"
FRASE_CONFIRMACION = "ELIMINAR"


def _contexto():
    return {"contacto": CONTACTO_EMAIL, "actualizado": ULTIMA_ACTUALIZACION}


@bp.route("/robots.txt")
def robots():
    base = request.url_root.rstrip("/")
    # Las pantallas con datos del negocio son privadas (requieren sesión): se piden fuera del índice por prolijidad
    lineas = ["User-agent: *", "Allow: /", "Allow: /terminos", "Allow: /privacidad", "Allow: /planes",
              "Disallow: /api/", "Disallow: /admin", "Disallow: /cuenta/", f"Sitemap: {base}/sitemap.xml"]
    cuerpo = chr(10).join(lineas) + chr(10)
    return Response(cuerpo, mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/planes", "/terminos", "/privacidad"))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', mimetype="application/xml")


@bp.route("/terminos")
def terminos():
    return render_template("legal.html", pagina="terminos", titulo="Términos y condiciones", **_contexto())


@bp.route("/privacidad")
def privacidad():
    return render_template("legal.html", pagina="privacidad", titulo="Política de privacidad", **_contexto())


def eliminar_usuario(usuario_id, conexion=None):
    """
    Borra al usuario y TODO lo suyo. Todas las tablas cuelgan de `usuarios` con ON DELETE CASCADE (usuarios → cuentas_meli → ventas,
    publicaciones, tokens, reclamos, costos…), así que una sola sentencia no deja nada. Devuelve la cantidad de usuarios borrados (0 o 1).
    Con `conexion` se puede probar dentro de una transacción y revertirla.
    """
    propia = conexion is None
    conexion = conexion or db.obtener_conexion_admin()
    try:
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))
        borrados = cursor.rowcount
        if propia:
            conexion.commit()
        return borrados
    except Exception:
        if propia:
            conexion.rollback()
        raise
    finally:
        if propia:
            db.liberar_conexion_admin(conexion)


@bp.route("/cuenta/eliminar", methods=["GET", "POST"])
@login_requerido
def cuenta_eliminar():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT email, plan, mp_suscripcion_id FROM usuarios WHERE id = %s", (g.usuario_id,))
        email, plan, mp_id = cursor.fetchone()

    es_dueno = config.es_admin(email)
    if request.method == "GET":
        return render_template("cuenta_eliminar.html", email=email, plan=plan, con_suscripcion=bool(mp_id) and plan in ("base", "elite"),
                               es_dueno=es_dueno, frase=FRASE_CONFIRMACION, contacto=CONTACTO_EMAIL)

    if es_dueno:
        flash("La cuenta del administrador no se elimina desde acá.")
        return redirect(url_for("legal.cuenta_eliminar"))
    if (request.form.get("confirmacion") or "").strip().upper() != FRASE_CONFIRMACION:
        flash(f"Para confirmar, escribí {FRASE_CONFIRMACION}.")
        return redirect(url_for("legal.cuenta_eliminar"))

    # Si hay una suscripción paga, se cancela primero: no se puede borrar y seguir cobrando.
    if mp_id and plan in ("base", "elite") and not pagos.cancelar_suscripcion(mp_id):
        flash(f"No pudimos cancelar tu suscripción en Mercado Pago, así que no eliminamos nada. Probá de nuevo o escribinos a {CONTACTO_EMAIL}.")
        return redirect(url_for("legal.cuenta_eliminar"))

    usuario_id = g.usuario_id
    eliminar_usuario(usuario_id)
    print(f"[Cuenta] 🗑️ Usuario {usuario_id} eliminó su cuenta y todos sus datos.")
    cerrar_sesion()
    return redirect(url_for("legal.cuenta_eliminada"))


@bp.route("/cuenta/eliminada")
def cuenta_eliminada():
    return render_template("errores.html", codigo="✓", titulo="Tu cuenta se eliminó",
                           detalle="Borramos tu cuenta y todos tus datos de CoreLux. Podés desconectar la aplicación también desde tu cuenta de Mercado Libre. ¡Gracias por haber probado CoreLux!",
                           logueado=False)

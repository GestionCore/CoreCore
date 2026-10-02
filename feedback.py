"""
Comentarios de los usuarios dentro de la app. Un usuario escribe desde el menú ("Enviar un comentario"), queda guardado con la pantalla desde la que escribió y la
versión que corría, y quien administra los lee en /admin/feedback. Es el canal con las personas de la beta: mucho más fácil que un mail, y llega con contexto.
"""
import logging
import re

from flask import Blueprint, abort, g, jsonify, render_template, request

import db
from auth.middleware import admin_requerido, login_requerido
from seguridad import VERSION
from utils import ARGENTINA

log = logging.getLogger("corelux.feedback")
bp = Blueprint("feedback", __name__)

TIPOS = {"idea": "Una idea", "problema": "Algo no anda", "pregunta": "Una pregunta"}
MIN_LARGO, MAX_LARGO = 5, 2000


def validar(tipo, mensaje):
    """(tipo, mensaje limpio, error): error es None si está todo bien."""
    mensaje = re.sub(r"\n{3,}", "\n\n", (mensaje or "").strip())
    if tipo not in TIPOS:
        return None, None, "Elegí de qué se trata."
    if len(mensaje) < MIN_LARGO:
        return None, None, "Contanos un poco más."
    if len(mensaje) > MAX_LARGO:
        return None, None, f"Es muy largo (máximo {MAX_LARGO} caracteres)."
    return tipo, mensaje, None


@bp.route("/api/feedback", methods=["POST"])
@login_requerido
def enviar():
    datos = request.get_json(silent=True) or {}
    tipo, mensaje, error = validar(datos.get("tipo"), datos.get("mensaje"))
    if error:
        return jsonify({"ok": False, "detalle": error}), 400
    pantalla = str(datos.get("pantalla") or "")[:200]
    navegador = (request.headers.get("User-Agent") or "")[:300]
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        conexion.cursor().execute(
            "INSERT INTO feedback (usuario_id, cuenta_id, tipo, mensaje, pantalla, navegador, version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (g.usuario_id, g.cuenta_id, tipo, mensaje, pantalla, navegador, VERSION),
        )
    return jsonify({"ok": True})


def listar_para_admin(solo_pendientes=False, limite=200):
    """Todos los comentarios (conexion_admin: ve los de todos los usuarios), los más nuevos primero."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(f"""
            SELECT f.id, f.tipo, f.mensaje, f.pantalla, f.version, f.atendido, f.creado_en, u.email, c.nickname
            FROM feedback f JOIN usuarios u ON u.id = f.usuario_id LEFT JOIN cuentas_meli c ON c.id = f.cuenta_id
            {"WHERE NOT f.atendido" if solo_pendientes else ""}
            ORDER BY f.atendido, f.creado_en DESC LIMIT %s
        """, (limite,))
        return [{"id": i, "tipo": t, "tipo_texto": TIPOS.get(t, t), "mensaje": m, "pantalla": p, "version": v, "atendido": a,
                 "cuando": cr.astimezone(ARGENTINA), "email": e, "cuenta": n} for i, t, m, p, v, a, cr, e, n in cursor.fetchall()]


def contar_pendientes():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COUNT(*) FROM feedback WHERE NOT atendido")
        return cursor.fetchone()[0]


@bp.route("/admin/feedback")
@login_requerido
@admin_requerido
def admin_feedback():
    return render_template("admin_feedback.html", comentarios=listar_para_admin(), active_nav="admin")


@bp.route("/admin/feedback/<int:comentario_id>/atendido", methods=["POST"])
@login_requerido
@admin_requerido
def marcar_atendido(comentario_id):
    atendido = bool((request.get_json(silent=True) or {}).get("atendido", True))
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE feedback SET atendido = %s WHERE id = %s", (atendido, comentario_id))
        if not cursor.rowcount:
            abort(404)
    return jsonify({"ok": True, "atendido": atendido})

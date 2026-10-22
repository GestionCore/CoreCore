"""
Respuestas guardadas para las preguntas de compradores (migración 0053, tabla `plantillas_respuesta`).

Cada cuenta guarda las respuestas que repite («Hay stock», «Envíos»…) con un nombre corto y las usa con un clic en cada pregunta. El texto puede llevar tres variables que se completan solas
según la pregunta: {saludo} (Buen día / Buenas tardes / Buenas noches, por la hora de Argentina), {producto} (el título de la publicación) y {precio} (su precio actual). Si una variable no se
puede completar (una publicación sin precio cargado) se deja escrita y la pantalla avisa que falta completarla: nunca se publica «{precio}» tal cual.

Los textos los escribe la persona; CoreLux no agrega promesas ni datos que no sean los de su propia publicación.
"""
import re
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from psycopg.errors import UndefinedTable

import db
from auth.middleware import login_requerido
from utils import ARGENTINA, formatear_moneda

bp = Blueprint("plantillas_respuesta", __name__)

MAX_PLANTILLAS = 30
MAX_TITULO = 60
MAX_TEXTO = 2000                      # lo que acepta Mercado Libre para una respuesta (ver api_preguntas_responder)
VARIABLES = {
    "saludo": "Buen día, Buenas tardes o Buenas noches, según la hora",
    "producto": "el título de la publicación por la que preguntaron",
    "precio": "el precio actual de esa publicación",
}
RE_VARIABLE = re.compile(r"\{(\w+)\}")

# Ejemplos para empezar (la persona los agrega y los edita): nada de promesas concretas, solo lo que casi cualquier vendedor puede decir
SUGERIDAS = (
    {"titulo": "Hay stock", "texto": "{saludo}! Sí, tenemos {producto} disponible. Podés comprarlo ahora y lo despachamos a la brevedad. ¡Gracias por preguntar!"},
    {"titulo": "Envíos", "texto": "{saludo}! Hacemos envíos con Mercado Envíos. El costo y el plazo los ves al poner tu código postal en la publicación. ¡Gracias por tu consulta!"},
    {"titulo": "Cualquier problema", "texto": "{saludo}! Si tenés algún inconveniente con tu compra, escribinos por Mercado Libre y lo resolvemos. ¡Gracias por elegirnos!"},
)


def validar(titulo, texto):
    """(titulo, texto, error): limpios, y error es None si está todo bien."""
    titulo = re.sub(r"\s+", " ", (titulo or "").strip())
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())
    if not titulo:
        return None, None, "Ponele un nombre corto para encontrarla rápido (por ejemplo: Hay stock)."
    if len(titulo) > MAX_TITULO:
        return None, None, f"El nombre es muy largo (máximo {MAX_TITULO} caracteres)."
    if not texto:
        return None, None, "Escribí el texto de la respuesta."
    if len(texto) > MAX_TEXTO:
        return None, None, f"La respuesta es muy larga: Mercado Libre acepta hasta {MAX_TEXTO} caracteres."
    desconocidas = sorted({v for v in RE_VARIABLE.findall(texto) if v not in VARIABLES})
    if desconocidas:
        usables = ", ".join("{" + v + "}" for v in VARIABLES)
        return None, None, f"No existe {', '.join('{' + v + '}' for v in desconocidas)}. Las que se completan solas son {usables}."
    return titulo, texto, None


def saludo(ahora=None):
    """Buen día hasta el mediodía, Buenas tardes hasta las 20 y Buenas noches después (hora de Argentina)."""
    hora = (ahora or datetime.now(ARGENTINA)).hour
    return "Buen día" if 6 <= hora < 12 else ("Buenas tardes" if 12 <= hora < 20 else "Buenas noches")


def aplicar(texto, valores):
    """El texto con las variables que se conocen ya completas. Devuelve (texto, [variables que quedaron sin completar])."""
    def _reemplazo(m):
        valor = valores.get(m.group(1))
        return str(valor) if valor else m.group(0)
    resultado = RE_VARIABLE.sub(_reemplazo, texto)
    return resultado, sorted({v for v in RE_VARIABLE.findall(resultado) if v in VARIABLES})


def _fila(f):
    return {"id": f[0], "titulo": f[1], "texto": f[2], "usos": f[3]}


def listar(cursor, cuenta_id):
    cursor.execute("SELECT id, titulo, texto, usos FROM plantillas_respuesta WHERE cuenta_id = %s ORDER BY usos DESC, lower(titulo), id", (cuenta_id,))
    return [_fila(f) for f in cursor.fetchall()]


def crear(cursor, cuenta_id, titulo, texto):
    """(plantilla, error). Tope de MAX_PLANTILLAS por cuenta."""
    titulo, texto, error = validar(titulo, texto)
    if error:
        return None, error
    cursor.execute("SELECT COUNT(*) FROM plantillas_respuesta WHERE cuenta_id = %s", (cuenta_id,))
    if cursor.fetchone()[0] >= MAX_PLANTILLAS:
        return None, f"Ya tenés {MAX_PLANTILLAS} respuestas guardadas: borrá alguna para agregar otra."
    cursor.execute("INSERT INTO plantillas_respuesta (cuenta_id, titulo, texto) VALUES (%s, %s, %s) RETURNING id, titulo, texto, usos", (cuenta_id, titulo, texto))
    return _fila(cursor.fetchone()), None


def actualizar(cursor, cuenta_id, plantilla_id, titulo, texto):
    titulo, texto, error = validar(titulo, texto)
    if error:
        return None, error
    cursor.execute(
        "UPDATE plantillas_respuesta SET titulo = %s, texto = %s, actualizada_en = now() WHERE id = %s AND cuenta_id = %s RETURNING id, titulo, texto, usos",
        (titulo, texto, plantilla_id, cuenta_id))
    fila = cursor.fetchone()
    return (_fila(fila), None) if fila else (None, "Esa respuesta ya no existe.")


def borrar(cursor, cuenta_id, plantilla_id):
    cursor.execute("DELETE FROM plantillas_respuesta WHERE id = %s AND cuenta_id = %s", (plantilla_id, cuenta_id))
    return cursor.rowcount == 1


def valores_de_la_pregunta(cursor, cuenta_id, question_id, ahora=None):
    """Lo que se conoce de ESA pregunta para completar las variables. Lo que no hay (sin precio cargado) no se inventa: simplemente no está."""
    cursor.execute(
        """SELECT COALESCE(pp.titulo, ''), COALESCE(pp.precio, 0)
           FROM preguntas_pendientes p LEFT JOIN productos_padre pp ON pp.id_meli = p.item_id AND pp.cuenta_id = p.cuenta_id
           WHERE p.cuenta_id = %s AND p.question_id = %s""", (cuenta_id, str(question_id)))
    fila = cursor.fetchone()
    valores = {"saludo": saludo(ahora)}
    if fila:
        if fila[0]:
            valores["producto"] = fila[0]
        if float(fila[1] or 0) > 0:
            valores["precio"] = "$" + formatear_moneda(float(fila[1]))
    return valores


def usar(cursor, cuenta_id, plantilla_id, question_id, ahora=None):
    """(texto ya completo, variables sin completar, error): la respuesta lista para pegar en la pregunta; suma un uso (las más usadas salen primero)."""
    cursor.execute("UPDATE plantillas_respuesta SET usos = usos + 1 WHERE id = %s AND cuenta_id = %s RETURNING texto", (plantilla_id, cuenta_id))
    fila = cursor.fetchone()
    if not fila:
        return None, [], "Esa respuesta ya no existe."
    texto, sin_completar = aplicar(fila[0], valores_de_la_pregunta(cursor, cuenta_id, question_id, ahora))
    return texto, sin_completar, None


# ── Rutas ──────────────────────────────────────────────────────────────────────
@bp.route("/api/preguntas/plantillas")
@login_requerido
def api_listar():
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            plantillas = listar(conexion.cursor(), g.cuenta_id)
    except UndefinedTable:                       # la migración 0053 todavía no se aplicó (justo antes de desplegar): Preguntas sigue andando, sin respuestas guardadas
        plantillas = []
    return jsonify({"plantillas": plantillas, "variables": VARIABLES, "sugeridas": [] if plantillas else list(SUGERIDAS), "max": MAX_PLANTILLAS, "max_texto": MAX_TEXTO})


@bp.route("/api/preguntas/plantillas", methods=["POST"])
@login_requerido
def api_crear():
    datos = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        plantilla, error = crear(conexion.cursor(), g.cuenta_id, datos.get("titulo"), datos.get("texto"))
    if error:
        return jsonify({"ok": False, "detalle": error}), 400
    return jsonify({"ok": True, "plantilla": plantilla})


@bp.route("/api/preguntas/plantillas/<int:plantilla_id>", methods=["POST"])
@login_requerido
def api_actualizar(plantilla_id):
    datos = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        plantilla, error = actualizar(conexion.cursor(), g.cuenta_id, plantilla_id, datos.get("titulo"), datos.get("texto"))
    if error:
        return jsonify({"ok": False, "detalle": error}), 400
    return jsonify({"ok": True, "plantilla": plantilla})


@bp.route("/api/preguntas/plantillas/<int:plantilla_id>/borrar", methods=["POST"])
@login_requerido
def api_borrar(plantilla_id):
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        borrada = borrar(conexion.cursor(), g.cuenta_id, plantilla_id)
    return jsonify({"ok": borrada, "detalle": None if borrada else "Esa respuesta ya no existe."}), (200 if borrada else 404)


@bp.route("/api/preguntas/plantillas/<int:plantilla_id>/usar", methods=["POST"])
@login_requerido
def api_usar(plantilla_id):
    datos = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        texto, sin_completar, error = usar(conexion.cursor(), g.cuenta_id, plantilla_id, datos.get("question_id"))
    if error:
        return jsonify({"ok": False, "detalle": error}), 404
    return jsonify({"ok": True, "texto": texto, "sin_completar": sin_completar})

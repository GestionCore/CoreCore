"""
Registro de actividad: deja constancia de las acciones que cambian datos reales o plata.

Uso, debajo de @login_requerido:

    @app.route("/actualizar_precios_masivo", methods=["POST"])
    @login_requerido
    @auditar("precios_masivo")
    def actualizar_precios_masivo(): ...

Se registra solo si la acción salió bien (respuesta < 400 y, si es JSON, sin "ok": false). Registrar nunca rompe la acción: si la tabla o la
base fallan, queda en el log y el usuario no se entera. Pantalla con el historial en /cuenta/actividad.
"""
import json
import logging
import re
from functools import wraps

from flask import Blueprint, Response, g, jsonify, render_template, request

import db
from auth.middleware import login_requerido
from seguridad import ip_del_cliente
from utils import ARGENTINA

log = logging.getLogger("corelux.auditoria")
bp = Blueprint("auditoria", __name__)

TAMANO_MAXIMO = 3000
_SECRETO = re.compile(r"token|password|contrase|clave|secret|authorization", re.IGNORECASE)

ETIQUETAS = {
    "precios_masivo": "Cambio de precios masivo",
    "stock_masivo": "Cambio de stock masivo",
    "publicaciones_reactivar": "Publicaciones reactivadas",
    "precios_guiado": "Precios cambiados al recomendado",
    "precios_ajuste": "Precios subidos o bajados un porcentaje",
    "descuento_crear": "Descuento creado",
    "descuento_eliminar": "Descuento eliminado",
    "publicacion_editar": "Publicación editada",
    "publicacion_descripcion": "Descripción editada",
    "publicacion_atributos": "Atributos editados",
    "pregunta_responder": "Pregunta respondida",
    "costos_chat": "Costos cargados por chat",
    "costo_producto": "Costo de un producto",
    "costos_masivo": "Costos guardados en bloque",
    "costos_importar": "Costos importados desde planilla",
    "gasto_agregar": "Gasto agregado",
    "gasto_eliminar": "Gasto eliminado",
    "venta_manual_agregar": "Venta manual agregada",
    "venta_manual_eliminar": "Venta manual eliminada",
    "flex_umbrales": "Umbrales de Flex guardados",
    "flex_aplicar": "Costo de Flex aplicado a ventas",
    "flex_zona": "Zona de Flex cambiada",
    "monotributo_declarar": "Categoría de Monotributo declarada",
    "plan_cambiar": "Plan cambiado (admin)",
    "usuario_activar": "Usuario activado o desactivado (admin)",
    "trial_extender": "Prueba extendida (admin)",
    "suscripcion_cancelar": "Suscripción cancelada",
}


def _sin_secretos(valor):
    if isinstance(valor, dict):
        return {k: "***" if _SECRETO.search(str(k)) else _sin_secretos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sin_secretos(v) for v in valor]
    return valor


def _resumen_del_pedido():
    """Lo que se mandó, sin secretos y acotado: si es muy grande se guarda solo cuántos elementos traía."""
    datos = request.get_json(silent=True)
    if datos is None:
        datos = request.form.to_dict() if request.form else None
    if datos is None:
        return None
    datos = _sin_secretos(datos)
    if len(json.dumps(datos, default=str)) <= TAMANO_MAXIMO:
        return datos
    return {"truncado": True, "elementos": len(datos) if hasattr(datos, "__len__") else None}


def _salio_bien(respuesta):
    """(ok, codigo): una respuesta < 400 cuenta como éxito salvo que sea JSON con "ok": false."""
    codigo = 200
    if isinstance(respuesta, tuple):
        if len(respuesta) > 1 and isinstance(respuesta[1], int):
            codigo = respuesta[1]
        respuesta = respuesta[0]
    if isinstance(respuesta, Response):
        codigo = respuesta.status_code if codigo == 200 else codigo
        if respuesta.is_json:
            cuerpo = respuesta.get_json(silent=True)
            if isinstance(cuerpo, dict) and cuerpo.get("ok") is False:
                return False, codigo
    elif isinstance(respuesta, dict) and respuesta.get("ok") is False:
        return False, codigo
    return codigo < 400, codigo


def registrar(accion, detalle=None, usuario_id=None, cuenta_id=None):
    """Guarda una fila de actividad. Nunca lanza: una falla de auditoría no debe frenar la acción del usuario."""
    try:
        usuario_id = usuario_id or g.get("usuario_id")
        cuenta_id = cuenta_id or g.get("cuenta_id")
        if not usuario_id:
            return
        ip = ip_del_cliente() if request else None
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            conexion.cursor().execute(
                "INSERT INTO auditoria (usuario_id, cuenta_id, accion, detalle, ip) VALUES (%s, %s, %s, %s::jsonb, %s)",
                (usuario_id, cuenta_id, accion, json.dumps(detalle or {}, default=str), ip),
            )
    except Exception as e:
        log.warning("No se pudo registrar la actividad '%s': %s", accion, e)


def auditar(accion):
    """Decorador: registra la acción después de que la vista respondió bien."""
    def decorador(vista):
        @wraps(vista)
        def envoltorio(*args, **kwargs):
            respuesta = vista(*args, **kwargs)
            try:
                ok, _codigo = _salio_bien(respuesta)
                if ok:
                    detalle = {"ruta": request.path}
                    if kwargs:
                        detalle["ids"] = kwargs
                    pedido = _resumen_del_pedido()
                    if pedido is not None:
                        detalle["pedido"] = pedido
                    registrar(accion, detalle)
            except Exception as e:
                log.warning("Auditoría de '%s' falló: %s", accion, e)
            return respuesta
        return envoltorio
    return decorador


def listar(usuario_id, cuenta_id, limite=100):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT accion, detalle, ip, creado_en, cuenta_id FROM auditoria WHERE usuario_id = %s ORDER BY creado_en DESC LIMIT %s",
            (usuario_id, limite),
        )
        return [
            {"accion": a, "etiqueta": ETIQUETAS.get(a, a.replace("_", " ").capitalize()), "detalle": d or {}, "ip": ip, "cuando": c.astimezone(ARGENTINA), "cuenta_id": cu}
            for a, d, ip, c, cu in cursor.fetchall()
        ]


@bp.route("/cuenta/actividad")
@login_requerido
def actividad():
    return render_template("actividad.html", eventos=listar(g.usuario_id, g.cuenta_id), active_nav="cuenta")


@bp.route("/api/cuenta/actividad")
@login_requerido
def api_actividad():
    eventos = listar(g.usuario_id, g.cuenta_id, limite=min(int(request.args.get("limite", 100)), 500))
    for e in eventos:
        e["cuando"] = e["cuando"].isoformat()
    return jsonify({"ok": True, "eventos": eventos})


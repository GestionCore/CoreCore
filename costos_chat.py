"""
Costos por chat — la IA convierte una descripción en lenguaje natural
("el alquiler me sale 150 mil por mes desde julio") en un gasto
estructurado, preguntando lo que falte (sobre todo el período) antes
de proponer guardar nada. Nunca escribe en la base directamente: solo
devuelve una PROPUESTA que el usuario tiene que confirmar a mano desde
el frontend, llamando a `confirmar_y_guardar` — así un malentendido de
la IA nunca termina como un gasto real sin que la persona lo revise.
"""
import json
import re
from datetime import datetime
import db
import ia_asistente

PROMPT_SISTEMA = """Sos un asistente que ayuda a cargar gastos operativos de un negocio de indumentaria en Mercado Libre. Tu única tarea es extraer datos estructurados de lo que te describe el usuario, o preguntar lo que falte — nunca conversás de otra cosa.

Hoy es {fecha_hoy}.

Por cada mensaje del usuario, respondé ÚNICAMENTE con un objeto JSON (nada de texto antes o después, ni bloques de código), con una de estas dos formas:

1) Si falta información para cargar el gasto (sobre todo si no dijo desde cuándo aplica, o si el monto es ambiguo):
{{"accion": "preguntar", "pregunta": "una sola pregunta corta y concreta"}}

2) Si ya tenés todo lo necesario:
{{"accion": "confirmar", "concepto": "texto corto describiendo el gasto", "monto": 150000.0, "categoria": "fijo" o "variable", "recurrente": true o false, "fecha_desde": "YYYY-MM-DD", "fecha_fin": null o "YYYY-MM-DD"}}

Reglas:
- "recurrente": true cuando el usuario describe algo que se repite todos los meses (alquiler, sueldo, un abono) — en ese caso "monto" es el importe MENSUAL.
- "recurrente": false para un gasto de una sola vez (una compra puntual, una reparación).
- "categoria" "fijo" = no cambia según cuánto vendés (alquiler, sueldos, abonos). "variable" = depende del volumen de venta (insumos, comisiones extra, envíos por fuera de MeLi).
- Si el usuario no aclaró desde cuándo aplica un gasto recurrente, SIEMPRE preguntá — no asumas "desde hoy" en silencio.
- Si no aclaró si es fijo o variable, decidilo vos según el tipo de gasto descrito, no preguntes por eso específicamente.
- "fecha_desde" para un gasto NO recurrente es la fecha en que se hizo/se hace ese gasto.
- Nunca inventes un monto ni una fecha que el usuario no haya dado o confirmado."""


def _limpiar_y_parsear_json(texto):
    texto = texto.strip()
    texto = re.sub(r'^```(?:json)?\s*|\s*```$', '', texto, flags=re.MULTILINE).strip()
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r'\{.*\}', texto, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def procesar_mensaje(historial_mensajes):
    """
    historial_mensajes: lista de {"role": "user"|"assistant", "content": "..."}
    con el historial completo de ESTA conversación de carga (se reinicia
    cada vez que se confirma o se cierra el chat).
    """
    prompt = PROMPT_SISTEMA.format(fecha_hoy=datetime.now().strftime("%Y-%m-%d"))
    ok, respuesta = ia_asistente.preguntar_ia_conversacion(prompt, historial_mensajes, max_tokens=400, temperatura=0.2)

    if not ok:
        return {"accion": "error", "mensaje": f"No pude conectar con la IA ({respuesta}). Podés cargar el gasto a mano en el formulario de abajo."}

    parseado = _limpiar_y_parsear_json(respuesta)
    if not parseado or "accion" not in parseado:
        return {"accion": "preguntar", "pregunta": "No terminé de entender eso — ¿me lo describís de otra forma? Por ejemplo: \"el alquiler sale 150 mil por mes desde julio\"."}

    if parseado["accion"] == "confirmar":
        faltantes = [campo for campo in ("concepto", "monto", "categoria", "recurrente", "fecha_desde") if campo not in parseado or parseado[campo] is None]
        if faltantes:
            return {"accion": "preguntar", "pregunta": "Me falta un dato más — ¿me confirmás el monto y desde cuándo aplica?"}

    return parseado


def confirmar_y_guardar(usuario_id, cuenta_id, propuesta):
    campos_requeridos = ("concepto", "monto", "categoria", "recurrente", "fecha_desde")
    if any(c not in propuesta for c in campos_requeridos):
        return False, "Faltan datos en la propuesta."
    if propuesta["categoria"] not in ("fijo", "variable"):
        return False, "Categoría inválida."
    try:
        monto = float(propuesta["monto"])
        datetime.strptime(propuesta["fecha_desde"], "%Y-%m-%d")
        if propuesta.get("fecha_fin"):
            datetime.strptime(propuesta["fecha_fin"], "%Y-%m-%d")
    except (ValueError, TypeError):
        return False, "Monto o fecha con formato inválido."

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha, recurrente, fecha_fin)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (cuenta_id, propuesta["concepto"], propuesta["categoria"], monto,
              propuesta["fecha_desde"], bool(propuesta["recurrente"]), propuesta.get("fecha_fin")))
    return True, "ok"

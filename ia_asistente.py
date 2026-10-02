import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Cualquier proveedor compatible con el formato de Chat Completions de
# OpenAI sirve acá (DeepSeek, OpenRouter, Groq, etc.) — el código de
# más abajo no le pregunta nada a un proveedor puntual.
IA_API_KEY = os.getenv("IA_API_KEY", "")
IA_BASE_URL = os.getenv("IA_BASE_URL", "https://api.deepseek.com")
IA_MODEL = os.getenv("IA_MODEL", "deepseek-flash")

MAXIMO_TOKENS = 4000


def parametros_extra():
    """
    Parámetros adicionales para el pedido al proveedor. deepseek-flash es un modelo de RAZONAMIENTO: gasta los max_tokens pensando y, con un
    presupuesto chico (200), muchas veces no llega a escribir la respuesta (finish_reason "length" y contenido vacío) además de tardar ~8 s en
    lugar de ~1 s. Para DeepSeek se apaga el razonamiento, que estas tareas (redactar un aviso, resumir datos, extraer un gasto) no necesitan.
    IA_PARAMETROS_EXTRA (JSON) lo reemplaza para otro proveedor o para volver a activarlo: "{}" no manda nada.
    """
    crudo = os.getenv("IA_PARAMETROS_EXTRA")
    if crudo is not None:
        try:
            extra = json.loads(crudo or "{}")
            return extra if isinstance(extra, dict) else {}
        except ValueError:
            print("[IA] ⚠️ IA_PARAMETROS_EXTRA no es un JSON válido: se ignora.")
            return {}
    return {"thinking": {"type": "disabled"}} if "deepseek" in IA_BASE_URL.lower() else {}


def preguntar_ia(prompt_sistema, prompt_usuario, max_tokens=500, temperatura=0.4):
    """Versión de un solo turno (ya existente, sin cambios de comportamiento)."""
    return preguntar_ia_conversacion(prompt_sistema, [{"role": "user", "content": prompt_usuario}], max_tokens, temperatura)


def preguntar_ia_conversacion(prompt_sistema, historial_mensajes, max_tokens=500, temperatura=0.4, reintentos=2):
    """
    Igual que preguntar_ia, pero acepta una lista de mensajes previos
    ({"role": "user"|"assistant", "content": "..."}) para que el modelo
    tenga el hilo de la conversación, no solo el último mensaje.

    Algunos modelos devuelven de vez en cuando una respuesta 200 pero
    sin contenido de texto. Reintentamos un par de veces antes de
    darnos por vencidos, porque casi siempre el reintento sí trae
    contenido.
    """
    if not IA_API_KEY:
        return False, "Falta configurar IA_API_KEY en el archivo .env."

    import time
    ultimo_error = "Error desconocido."
    for intento in range(reintentos + 1):
        # Si la respuesta vino vacía, a veces es porque el presupuesto se agotó antes de escribir (modelos que razonan): cada reintento lo triplica.
        ok, resultado = _intentar_una_vez(prompt_sistema, historial_mensajes, min(max_tokens * (3 ** intento), MAXIMO_TOKENS), temperatura)
        if ok:
            return True, resultado
        ultimo_error = resultado
        # Solo vale la pena reintentar cuando el problema fue "vino vacío"
        # — un error de credenciales o de red no se arregla reintentando.
        if "sin texto de contenido" not in resultado and "ninguna opción válida" not in resultado:
            break
        if intento < reintentos:
            print(f"[IA] ⚠️ Respuesta vacía (intento {intento + 1}/{reintentos + 1}) — reintentando...")
            time.sleep(0.8)

    return False, ultimo_error


def _intentar_una_vez(prompt_sistema, historial_mensajes, max_tokens, temperatura):
    try:
        resp = requests.post(
            f"{IA_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {IA_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": IA_MODEL,
                "messages": [{"role": "system", "content": prompt_sistema}] + historial_mensajes,
                "temperature": temperatura,
                "max_tokens": max_tokens,
                **parametros_extra(),
            },
            timeout=30
        )

        if resp.status_code != 200:
            try:
                error_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text[:200]
            print(f"[IA] ⚠️ Error del proveedor de IA: {resp.status_code} - {error_msg}")
            return False, f"Error comunicando con la IA: {error_msg}"

        data = resp.json()
        choices = data.get("choices")
        if choices and len(choices) > 0:
            mensaje = choices[0].get("message", {})
            contenido = mensaje.get("content")
            if contenido and isinstance(contenido, str) and contenido.strip():
                return True, contenido.strip()
            return False, "La IA respondió sin texto de contenido."

        return False, "La IA no devolvió ninguna opción válida."

    except requests.exceptions.Timeout:
        print("[IA] ❌ Timeout consultando al proveedor de IA.")
        return False, "Error comunicando con la IA: tiempo de espera agotado (Timeout)."
    except Exception as e:
        print(f"[IA] ❌ Error inesperado: {e}")
        return False, f"Error comunicando con la IA: {e}"

import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")


def preguntar_ia(prompt_sistema, prompt_usuario, max_tokens=500, temperatura=0.4):
    """Versión de un solo turno (ya existente, sin cambios de comportamiento)."""
    return preguntar_ia_conversacion(prompt_sistema, [{"role": "user", "content": prompt_usuario}], max_tokens, temperatura)


def preguntar_ia_conversacion(prompt_sistema, historial_mensajes, max_tokens=500, temperatura=0.4, reintentos=2):
    """
    Igual que preguntar_ia, pero acepta una lista de mensajes previos
    ({"role": "user"|"assistant", "content": "..."}) para que el modelo
    tenga el hilo de la conversación, no solo el último mensaje.

    El modelo gratuito de OpenRouter a veces devuelve una respuesta 200
    pero sin contenido de texto — es un problema conocido de los modelos
    "free", no un error de nuestro lado. Reintentamos un par de veces
    antes de darnos por vencidos, porque casi siempre el reintento sí
    trae contenido.
    """
    if not OPENROUTER_API_KEY:
        return False, "Falta configurar OPENROUTER_API_KEY en el archivo .env."

    import time
    ultimo_error = "Error desconocido."
    for intento in range(reintentos + 1):
        ok, resultado = _intentar_una_vez(prompt_sistema, historial_mensajes, max_tokens, temperatura)
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
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "system", "content": prompt_sistema}] + historial_mensajes,
                "temperature": temperatura,
                "max_tokens": max_tokens
            },
            timeout=30
        )

        if resp.status_code != 200:
            try:
                error_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text[:200]
            print(f"[IA] ⚠️ Error de OpenRouter: {resp.status_code} - {error_msg}")
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
        print("[IA] ❌ Timeout consultando OpenRouter.")
        return False, "Error comunicando con la IA: tiempo de espera agotado (Timeout)."
    except Exception as e:
        print(f"[IA] ❌ Error inesperado: {e}")
        return False, f"Error comunicando con la IA: {e}"

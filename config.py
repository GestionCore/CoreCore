"""
Configuración central de CoreLux — todo lo que viene de variables de
entorno vive acá, nunca hardcodeado en el resto del código.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Base de datos (Supabase / Postgres) ---
# Supabase te da esta cadena en Project Settings > Database > Connection String
# (usá la de "Session pooler" o "Transaction pooler" para producción, no la
# conexión directa, que tiene un límite bajo de conexiones simultáneas).
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Conexión separada, con un rol que tiene BYPASSRLS, usada ÚNICAMENTE por
# token_manager.py para leer/guardar los tokens de MeLi. La tabla
# meli_tokens tiene una política de RLS que bloquea TODO acceso desde el
# rol normal (ni SELECT ni INSERT) — a propósito, para que ningún otro
# código del proyecto pueda tocarla "sin querer". Creá este rol en
# Supabase (SQL Editor):
#   CREATE ROLE app_admin LOGIN PASSWORD '...' BYPASSRLS;
#   GRANT ALL ON meli_tokens TO app_admin;
DATABASE_URL_ADMIN = os.getenv("DATABASE_URL_ADMIN", "")

# --- Mercado Libre OAuth ---
MELI_CLIENT_ID = os.getenv("MELI_CLIENT_ID", "")
MELI_CLIENT_SECRET = os.getenv("MELI_CLIENT_SECRET", "")
MELI_REDIRECT_URI = os.getenv("MELI_REDIRECT_URI", "")  # ej: https://tu-subdominio.ngrok-free.app/callback
MELI_SITE_ID = os.getenv("MELI_SITE_ID", "MLA")

# --- IA (OpenRouter, para el mensaje "coach" de Logros) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

# --- Seguridad ---
# Clave de Flask para firmar la cookie de sesión — generá una real con:
#   python -c "import secrets; print(secrets.token_hex(32))"
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")

# Clave de cifrado para los tokens de MeLi guardados en la base — generá
# una real con:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# NUNCA la guardes en la base de datos ni en el repositorio — solo acá,
# como variable de entorno del servidor.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# --- Validación al arranque ---
# Sin esto, una variable vacía se manifiesta como un error 500 críptico
# recién cuando el usuario hace clic en algo puntual (ej: "session is
# unavailable because no secret key was set" al tocar "Conectar") — mucho
# más difícil de diagnosticar que frenar acá mismo, al arrancar, con un
# mensaje que dice exactamente qué falta.
_REQUERIDAS = {
    "DATABASE_URL": DATABASE_URL, "DATABASE_URL_ADMIN": DATABASE_URL_ADMIN,
    "MELI_CLIENT_ID": MELI_CLIENT_ID, "MELI_CLIENT_SECRET": MELI_CLIENT_SECRET,
    "MELI_REDIRECT_URI": MELI_REDIRECT_URI, "FLASK_SECRET_KEY": FLASK_SECRET_KEY,
    "TOKEN_ENCRYPTION_KEY": TOKEN_ENCRYPTION_KEY,
}
_faltantes = [nombre for nombre, valor in _REQUERIDAS.items() if not valor]
if _faltantes:
    raise RuntimeError(
        "Falta configurar en tu .env: " + ", ".join(_faltantes) + "\n"
        "Revisá que el archivo se llame exactamente '.env' (no '.env.txt') y esté en la misma carpeta que app.py, "
        "y que cada variable tenga un valor real después del '=' (sin comillas, sin espacios extra)."
    )

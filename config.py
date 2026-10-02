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

# --- IA (Chat IA, Costos por chat, mensaje "coach" de Logros) ---
# Cualquier proveedor compatible con el formato de Chat Completions de
# OpenAI sirve acá (DeepSeek, OpenRouter, Groq, etc.) — solo cambian
# estos 3 valores, el código no le pregunta a un proveedor puntual.
IA_API_KEY = os.getenv("IA_API_KEY", "")
IA_BASE_URL = os.getenv("IA_BASE_URL", "https://api.deepseek.com")
IA_MODEL = os.getenv("IA_MODEL", "deepseek-flash")

# --- Infraestructura F0: Redis + Sentry ---
# Redis: para Celery (cola de tareas + beat scheduler) y Flask-Caching.
# Opciones:
#   - Local Windows: descargá Memurai (https://www.memurai.com/) o usá Redis via WSL
#   - Cloud gratis: Upstash Redis (https://upstash.com/) — ideal para desarrollo
#   - Producción: Redis propio en el servidor Linux
# Formato: redis://[:password@]host:port/db  ó  rediss://... (TLS)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Sentry: monitoreo de errores en producción.
# Obtené tu DSN en https://sentry.io — el free tier cubre 5000 errores/mes.
# Dejá vacío en local si no querés enviar errores a Sentry durante desarrollo.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Flask-Caching: usa Redis si está disponible, SimpleCache como fallback para dev local.
CACHE_TYPE = os.getenv("CACHE_TYPE", "RedisCache")
CACHE_DEFAULT_TIMEOUT = int(os.getenv("CACHE_DEFAULT_TIMEOUT", "300"))
CACHE_KEY_PREFIX = "corelux_"

# --- Seguridad ---
# Clave de Flask para firmar la cookie de sesión — generá una real con:
#   python -c "import secrets; print(secrets.token_hex(32))"
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")
# Opcional: la clave (o varias, separadas por coma) que se usaba antes. Las sesiones firmadas con ella siguen valiendo, así que se puede
# rotar FLASK_SECRET_KEY sin desloguear a nadie (ver docs/RUNBOOK.md).
FLASK_SECRET_KEY_ANTERIOR = os.getenv("FLASK_SECRET_KEY_ANTERIOR", "")

# Clave de cifrado para los tokens de MeLi guardados en la base — generá
# una real con:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# NUNCA la guardes en la base de datos ni en el repositorio — solo acá,
# como variable de entorno del servidor.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
# Opcional: la clave (o varias, separadas por coma) que se usaba ANTES. Solo descifra; sirve para rotar TOKEN_ENCRYPTION_KEY sin
# desconectar a nadie (ver rotar_clave.py y docs/RUNBOOK.md).
TOKEN_ENCRYPTION_KEY_ANTERIOR = os.getenv("TOKEN_ENCRYPTION_KEY_ANTERIOR", "")

# --- Mercado Pago (pagos de suscripción de CoreLux) ---
# Credenciales PROPIAS de CoreLux en MercadoPago, para cobrar a los usuarios.
# No confundir con las credenciales de MeLi de cada usuario vendedor.
# Obtené el access token en https://www.mercadopago.com.ar/developers/panel
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")

DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# Panel de administración — email del dueño de CoreLux. Agregar a .env:
#   ADMIN_EMAIL=tu@email.com
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

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


# --- Validación al arrancar ---
VARIABLES_OBLIGATORIAS = ("DATABASE_URL", "DATABASE_URL_ADMIN", "MELI_CLIENT_ID", "MELI_CLIENT_SECRET", "MELI_REDIRECT_URI",
                          "FLASK_SECRET_KEY", "TOKEN_ENCRYPTION_KEY")
VARIABLES_RECOMENDADAS = {
    "SENTRY_DSN": "sin esto no te enterás de los errores en producción",
    "MP_ACCESS_TOKEN": "sin esto no se pueden cobrar las suscripciones",
    "IA_API_KEY": "sin esto no funcionan el chat, los costos por chat ni las respuestas sugeridas",
    "ADMIN_EMAIL": "sin esto nadie puede entrar a /admin",
}


def validar():
    """(faltan, recomendadas_faltantes): variables obligatorias vacías y recomendadas vacías con el motivo."""
    g = globals()
    faltan = [v for v in VARIABLES_OBLIGATORIAS if not g.get(v)]
    recomendadas = {v: motivo for v, motivo in VARIABLES_RECOMENDADAS.items() if not g.get(v)}
    return faltan, recomendadas

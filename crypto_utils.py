"""
Cifrado de los tokens de Mercado Libre antes de guardarlos en la base.
Usamos Fernet (cifrado simétrico) — la misma clave que cifra, descifra.
La clave vive SOLO en la variable de entorno del servidor, nunca en la
base de datos ni en el código.

Rotación de la clave: TOKEN_ENCRYPTION_KEY es la que cifra; TOKEN_ENCRYPTION_KEY_ANTERIOR (una o varias separadas por coma) solo sirve
para descifrar lo que se guardó antes. Así se puede cambiar la clave sin desconectar a nadie (ver docs/RUNBOOK.md y rotar_clave.py).
"""
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
import config


def _claves_anteriores():
    return [k.strip() for k in (getattr(config, "TOKEN_ENCRYPTION_KEY_ANTERIOR", "") or "").split(",") if k.strip()]


def _obtener_fernet():
    if not config.TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "Falta TOKEN_ENCRYPTION_KEY en las variables de entorno. "
            "Generá una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    claves = [config.TOKEN_ENCRYPTION_KEY.strip()] + _claves_anteriores()
    return MultiFernet([Fernet(k.encode()) for k in claves])


def cifrar(texto_plano):
    if not texto_plano:
        return None
    return _obtener_fernet().encrypt(texto_plano.encode()).decode()


def descifrar(texto_cifrado):
    if not texto_cifrado:
        return None
    try:
        return _obtener_fernet().decrypt(texto_cifrado.encode()).decode()
    except InvalidToken:
        # La clave de cifrado cambió, o el dato está corrupto — mejor
        # fallar explícito que devolver un token trucho que rompa cosas
        # más adelante de formas confusas.
        raise RuntimeError("No se pudo descifrar el token — ¿cambió TOKEN_ENCRYPTION_KEY sin dejar la anterior en TOKEN_ENCRYPTION_KEY_ANTERIOR?")


def recifrar(texto_cifrado):
    """Vuelve a cifrar con la clave vigente un valor cifrado con una anterior (lo que usa rotar_clave.py)."""
    if not texto_cifrado:
        return None
    try:
        return _obtener_fernet().rotate(texto_cifrado.encode()).decode()
    except InvalidToken:
        raise RuntimeError("No se pudo descifrar el valor con ninguna de las claves configuradas.")


def usa_la_clave_vigente(texto_cifrado):
    """True si el valor se descifra con la clave vigente sola (no hace falta rotarlo)."""
    try:
        Fernet(config.TOKEN_ENCRYPTION_KEY.strip().encode()).decrypt(texto_cifrado.encode())
        return True
    except InvalidToken:
        return False

"""
Cifrado de los tokens de Mercado Libre antes de guardarlos en la base.
Usamos Fernet (cifrado simétrico) — la misma clave que cifra, descifra.
La clave vive SOLO en la variable de entorno del servidor, nunca en la
base de datos ni en el código.
"""
from cryptography.fernet import Fernet, InvalidToken
import config


def _obtener_fernet():
    if not config.TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "Falta TOKEN_ENCRYPTION_KEY en las variables de entorno. "
            "Generá una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(config.TOKEN_ENCRYPTION_KEY.encode())


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
        raise RuntimeError("No se pudo descifrar el token — ¿cambió TOKEN_ENCRYPTION_KEY?")

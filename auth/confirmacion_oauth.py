"""
Confirmación antes de vincular una cuenta de Mercado Libre desde un enlace abierto en OTRO navegador.

El enlace de «conectar otra cuenta» se puede abrir en cualquier navegador (migración 0013) y es una credencial: quien lo complete queda vinculado al usuario que lo generó. Antes de
vincular se le muestra a la persona a QUÉ cuenta de CoreLux se va a vincular y con QUÉ cuenta de Mercado Libre, y la vinculación recién se hace si confirma (migración 0042: los permisos
quedan cifrados 10 minutos mientras decide). Así nadie queda vinculado sin enterarse.
"""
import secrets

import crypto_utils
import db

MINUTOS_DE_VIDA = 10


def enmascarar_email(email):
    """«diego@gmail.com» → «d***@gmail.com». Sin un email real (vacío o el provisorio hasta leer el de Mercado Libre) devuelve None."""
    email = (email or "").strip()
    if "@" not in email or email.endswith("@pendiente.corelux.app"):
        return None
    usuario, dominio = email.rsplit("@", 1)
    return f"{usuario[:1]}***@{dominio}"


def titular_de(usuario_id):
    """Cómo se le nombra, a quien confirma, la cuenta de CoreLux a la que se va a vincular: el email enmascarado, si no el nombre, si no un texto genérico."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT email, nombre FROM usuarios WHERE id = %s", (usuario_id,))
        fila = cursor.fetchone()
    if not fila:
        return "un usuario de CoreLux"
    return enmascarar_email(fila[0]) or (fila[1] or "").strip() or "un usuario de CoreLux"


def guardar(usuario_id, datos_meli, tokens):
    """Guarda (cifrados) los permisos que Mercado Libre acaba de dar y devuelve el token de un solo uso que viaja en el formulario de confirmación."""
    token = secrets.token_urlsafe(32)
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(f"DELETE FROM oauth_confirmaciones_pendientes WHERE creado_en < now() - interval '{MINUTOS_DE_VIDA} minutes'")
        cursor.execute(
            """INSERT INTO oauth_confirmaciones_pendientes
               (token, usuario_id, meli_user_id, nickname, site_id, access_token_cifrado, refresh_token_cifrado, expires_in)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (token, usuario_id, datos_meli["meli_user_id"], datos_meli.get("nickname"), datos_meli.get("site_id", "MLA"),
             crypto_utils.cifrar(tokens["access_token"]), crypto_utils.cifrar(tokens["refresh_token"]), int(tokens["expires_in"])),
        )
    return token


def tomar(token):
    """
    Gasta el token (se borra al leerlo: un solo uso) y devuelve {"usuario_id", "datos_meli", "tokens"}, o None si no existe, ya se usó o pasaron más de MINUTOS_DE_VIDA.
    """
    if not token:
        return None
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            f"""DELETE FROM oauth_confirmaciones_pendientes WHERE token = %s AND creado_en > now() - interval '{MINUTOS_DE_VIDA} minutes'
                RETURNING usuario_id, meli_user_id, nickname, site_id, access_token_cifrado, refresh_token_cifrado, expires_in""",
            (token,),
        )
        fila = cursor.fetchone()
    if not fila:
        return None
    usuario_id, meli_user_id, nickname, site_id, acceso, refresco, expira = fila
    return {
        "usuario_id": usuario_id,
        "datos_meli": {"meli_user_id": meli_user_id, "nickname": nickname, "site_id": site_id},
        "tokens": {"access_token": crypto_utils.descifrar(acceso), "refresh_token": crypto_utils.descifrar(refresco), "expires_in": expira},
    }

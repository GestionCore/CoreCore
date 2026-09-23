"""
Gestión de tokens de Mercado Libre, por cuenta. Reemplaza al viejo
token_manager.py de un solo usuario — ahora todo recibe `cuenta_id`.

Reglas que respeta (según lo que confirmó MeLi):
- El access_token dura ~6hs — antes de cada uso remoto lo validamos por
  vencimiento y lo refrescamos si hace falta, así el resto del código
  nunca tiene que pensar en esto.
- El refresh_token es DE UN SOLO USO — cada vez que refrescamos, MeLi nos
  da un refresh_token NUEVO, y ese es el que hay que guardar. Si
  guardáramos el viejo, el próximo refresh fallaría.
- Si el refresh da error `invalid_grant`, la cuenta quedó desconectada
  de verdad (el usuario revocó el permiso, cambió la clave, etc.) — no
  tiene sentido reintentar, hay que marcarla como desconectada y pedirle
  al usuario que vuelva a autorizar.
"""
from datetime import datetime, timezone, timedelta
import requests
import config
import crypto_utils
import db
from auth import oauth_meli

MARGEN_SEGURIDAD_MINUTOS = 5  # refrescamos un poco antes de que venza de verdad


class CuentaDesconectada(Exception):
    """
    Se lanza cuando MeLi confirma que la cuenta ya no está autorizada
    (invalid_grant). El código que llama a asegurar_token_valido debe
    capturar esto y mandar al usuario a reconectar, nunca dejar que
    reviente como un error genérico.
    """
    pass


def guardar_tokens(cuenta_id, access_token, refresh_token, expires_in_segundos):
    expira_en = datetime.now(timezone.utc) + timedelta(seconds=expires_in_segundos)
    access_cifrado = crypto_utils.cifrar(access_token)
    refresh_cifrado = crypto_utils.cifrar(refresh_token)

    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            INSERT INTO meli_tokens (cuenta_id, access_token_cifrado, refresh_token_cifrado, expira_en, actualizado_en)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (cuenta_id) DO UPDATE SET
                access_token_cifrado = excluded.access_token_cifrado,
                refresh_token_cifrado = excluded.refresh_token_cifrado,
                expira_en = excluded.expira_en,
                actualizado_en = now()
        """, (cuenta_id, access_cifrado, refresh_cifrado, expira_en))


def _marcar_cuenta_desconectada(cuenta_id):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM meli_tokens WHERE cuenta_id = %s", (cuenta_id,))
        cursor.execute("UPDATE cuentas_meli SET activa = false WHERE id = %s", (cuenta_id,))


def asegurar_token_valido(cuenta_id):
    """
    Devuelve un access_token listo para usar contra la API de MeLi,
    refrescándolo primero si hace falta. Lanza CuentaDesconectada si MeLi
    confirma que el permiso ya no es válido.
    """
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT access_token_cifrado, refresh_token_cifrado, expira_en FROM meli_tokens WHERE cuenta_id = %s", (cuenta_id,))
        fila = cursor.fetchone()

    if not fila:
        raise CuentaDesconectada(f"La cuenta {cuenta_id} no tiene tokens guardados — nunca se conectó o fue desconectada.")

    access_cifrado, refresh_cifrado, expira_en = fila
    ahora = datetime.now(timezone.utc)

    if expira_en - timedelta(minutes=MARGEN_SEGURIDAD_MINUTOS) > ahora:
        # Todavía válido, no hace falta tocar nada
        return crypto_utils.descifrar(access_cifrado)

    # Venció (o está por vencer) — lo refrescamos
    refresh_token = crypto_utils.descifrar(refresh_cifrado)
    ok, resultado = oauth_meli.refrescar_token(refresh_token)

    if not ok:
        if "invalid_grant" in str(resultado):
            _marcar_cuenta_desconectada(cuenta_id)
            raise CuentaDesconectada(f"MeLi invalidó el permiso de la cuenta {cuenta_id} (invalid_grant) — hay que reconectar.")
        # Otro tipo de error (red, 500 de MeLi, etc.) — no marcamos la
        # cuenta como desconectada por esto, podría ser transitorio.
        raise RuntimeError(f"No se pudo refrescar el token de la cuenta {cuenta_id}: {resultado}")

    # Guardamos el refresh_token NUEVO — el viejo ya no sirve (uso único)
    guardar_tokens(cuenta_id, resultado["access_token"], resultado["refresh_token"], resultado["expires_in"])
    return resultado["access_token"]


def llamar_api_meli(cuenta_id, metodo, url, **kwargs):
    """
    Envoltorio recomendado para cualquier llamada a la API de MeLi: arma
    el header Authorization solo, y si la respuesta viene 401 (token
    inválido por algún motivo raro no cubierto por la validación de
    vencimiento) reintenta UNA vez forzando un refresh.
    """
    access_token = asegurar_token_valido(cuenta_id)
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token}"

    resp = requests.request(metodo, url, headers=headers, **kwargs)

    if resp.status_code == 401:
        # Token rechazado igual — invalidamos el vencimiento en memoria y
        # forzamos un refresh real antes de reintentar una sola vez.
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute("UPDATE meli_tokens SET expira_en = now() WHERE cuenta_id = %s", (cuenta_id,))
        access_token = asegurar_token_valido(cuenta_id)
        headers["Authorization"] = f"Bearer {access_token}"
        resp = requests.request(metodo, url, headers=headers, **kwargs)

    return resp

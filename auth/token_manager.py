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

Y por lo mismo (refresh_token de un solo uso) el refresco se hace de a UNO por cuenta: cuando varios pedidos ven el token vencido al mismo tiempo (un Dashboard
dispara muchos a la vez; también el sincronizador y los webhooks), el primero refresca y los demás esperan y releen el token nuevo. Sin esto, el segundo gastaba el
refresh_token ya usado, MeLi contestaba `invalid_grant` y la cuenta se marcaba como desconectada sin estarlo. Se serializa en dos niveles: un candado por cuenta dentro
del proceso (los hilos/greenlets de un worker no ocupan conexiones esperando) y un advisory lock de Postgres entre procesos (hay 2 máquinas × 2 workers).
"""
import threading
from datetime import datetime, timezone, timedelta

import requests
from psycopg.errors import LockNotAvailable

import crypto_utils
import db
import meli_http
from auth import oauth_meli

MARGEN_SEGURIDAD_MINUTOS = 5  # refrescamos un poco antes de que venza de verdad

# Advisory lock de Postgres por cuenta: BASE + cuenta_id. BASE es un bigint que no choca con el del scheduler (ID_LOCK_SCHEDULER) ni con ningún otro lock de la app.
BASE_LOCK_REFRESCO = 4_200_000_000_000_000
ESPERA_MAXIMA_DEL_LOCK = "20s"            # si otro proceso tarda más que esto en refrescar, no se queda esperando para siempre
TIMEOUT_POR_DEFECTO = 15                  # segundos, para toda llamada a MeLi que no declare el suyo

_candados_locales = {}
_guarda_candados = threading.Lock()


class CuentaDesconectada(Exception):
    """
    Se lanza cuando MeLi confirma que la cuenta ya no está autorizada
    (invalid_grant). El código que llama a asegurar_token_valido debe
    capturar esto y mandar al usuario a reconectar, nunca dejar que
    reviente como un error genérico.
    """
    pass


def _candado_local(cuenta_id):
    """Un candado por cuenta dentro de este proceso (el diccionario guarda candados, no datos de la cuenta)."""
    with _guarda_candados:
        return _candados_locales.setdefault(cuenta_id, threading.Lock())


def _esta_vigente(expira_en):
    return expira_en - timedelta(minutes=MARGEN_SEGURIDAD_MINUTOS) > datetime.now(timezone.utc)


def _guardar_en(cursor, cuenta_id, access_token, refresh_token, expires_in_segundos):
    expira_en = datetime.now(timezone.utc) + timedelta(seconds=expires_in_segundos)
    cursor.execute("""
        INSERT INTO meli_tokens (cuenta_id, access_token_cifrado, refresh_token_cifrado, expira_en, actualizado_en)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (cuenta_id) DO UPDATE SET
            access_token_cifrado = excluded.access_token_cifrado,
            refresh_token_cifrado = excluded.refresh_token_cifrado,
            expira_en = excluded.expira_en,
            actualizado_en = now()
    """, (cuenta_id, crypto_utils.cifrar(access_token), crypto_utils.cifrar(refresh_token), expira_en))


def guardar_tokens(cuenta_id, access_token, refresh_token, expires_in_segundos):
    with db.conexion_admin() as conexion:
        _guardar_en(conexion.cursor(), cuenta_id, access_token, refresh_token, expires_in_segundos)


def _leer_tokens(cuenta_id):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT access_token_cifrado, refresh_token_cifrado, expira_en FROM meli_tokens WHERE cuenta_id = %s", (cuenta_id,))
        return cursor.fetchone()


def _sin_tokens(cuenta_id):
    return CuentaDesconectada(f"La cuenta {cuenta_id} no tiene tokens guardados — nunca se conectó o fue desconectada.")


def _refrescar_de_a_uno(cuenta_id, token_rechazado=None):
    """
    Refresca el token de la cuenta con el advisory lock tomado: si otro pedido (de este proceso o de otro) lo refrescó mientras esperábamos, se usa el suyo y no se
    gasta otro refresh_token. `token_rechazado` es el access_token que MeLi acaba de contestar con 401: se refresca aunque no haya vencido, salvo que ya lo hayan cambiado.
    """
    desconectada = False
    error = None
    try:
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", (ESPERA_MAXIMA_DEL_LOCK,))
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (BASE_LOCK_REFRESCO + int(cuenta_id),))
            cursor.execute("SELECT access_token_cifrado, refresh_token_cifrado, expira_en FROM meli_tokens WHERE cuenta_id = %s", (cuenta_id,))
            fila = cursor.fetchone()
            if not fila:
                raise _sin_tokens(cuenta_id)
            access_cifrado, refresh_cifrado, expira_en = fila
            access_actual = crypto_utils.descifrar(access_cifrado)

            # ¿Ya lo refrescó otro mientras esperábamos el lock?
            if token_rechazado is not None:
                if access_actual != token_rechazado:
                    return access_actual
            elif _esta_vigente(expira_en):
                return access_actual

            ok, resultado = oauth_meli.refrescar_token(crypto_utils.descifrar(refresh_cifrado))
            if ok:
                # Guardamos el refresh_token NUEVO — el viejo ya no sirve (uso único). Misma transacción que el lock: nadie ve el token a medias.
                _guardar_en(cursor, cuenta_id, resultado["access_token"], resultado["refresh_token"], resultado["expires_in"])
                return resultado["access_token"]

            if "invalid_grant" in str(resultado):
                cursor.execute("DELETE FROM meli_tokens WHERE cuenta_id = %s", (cuenta_id,))
                cursor.execute("UPDATE cuentas_meli SET activa = false WHERE id = %s", (cuenta_id,))
                desconectada = True          # se confirma la transacción al salir del bloque; el aviso se levanta después (si no, el error la desharía)
            else:
                # Otro tipo de error (red, 500 de MeLi, etc.) — no marcamos la cuenta como desconectada por esto, podría ser transitorio.
                error = resultado
    except LockNotAvailable:
        # Otro proceso estuvo refrescando más de lo esperable: se mira si ya dejó un token vigente en vez de esperar sin fin
        fila = _leer_tokens(cuenta_id)
        if fila and _esta_vigente(fila[2]):
            return crypto_utils.descifrar(fila[0])
        raise RuntimeError(f"No se pudo refrescar el token de la cuenta {cuenta_id}: otro proceso lo está haciendo y no terminó a tiempo.")

    if desconectada:
        raise CuentaDesconectada(f"MeLi invalidó el permiso de la cuenta {cuenta_id} (invalid_grant) — hay que reconectar.")
    raise RuntimeError(f"No se pudo refrescar el token de la cuenta {cuenta_id}: {error}")


def asegurar_token_valido(cuenta_id):
    """
    Devuelve un access_token listo para usar contra la API de MeLi,
    refrescándolo primero si hace falta. Lanza CuentaDesconectada si MeLi
    confirma que el permiso ya no es válido.
    """
    fila = _leer_tokens(cuenta_id)
    if not fila:
        raise _sin_tokens(cuenta_id)
    access_cifrado, _refresh_cifrado, expira_en = fila
    if _esta_vigente(expira_en):
        # Todavía válido, no hace falta tocar nada
        return crypto_utils.descifrar(access_cifrado)

    # Venció (o está por vencer): se refresca de a uno por cuenta
    with _candado_local(cuenta_id):
        return _refrescar_de_a_uno(cuenta_id)


def refrescar_token_rechazado(cuenta_id, access_token_rechazado):
    """MeLi contestó 401 con este token: se fuerza un refresh real, salvo que otro pedido ya lo haya cambiado (en ese caso se devuelve el nuevo)."""
    with _candado_local(cuenta_id):
        return _refrescar_de_a_uno(cuenta_id, token_rechazado=access_token_rechazado)


def llamar_api_meli(cuenta_id, metodo, url, **kwargs):
    """
    Envoltorio recomendado para cualquier llamada a la API de MeLi: arma
    el header Authorization solo, y si la respuesta viene 401 (token
    inválido por algún motivo raro no cubierto por la validación de
    vencimiento) reintenta UNA vez forzando un refresh.

    Sin un timeout explícito se usa TIMEOUT_POR_DEFECTO: sin él, una respuesta que nunca llega dejaba al worker esperando para siempre.
    """
    kwargs.setdefault("timeout", TIMEOUT_POR_DEFECTO)
    access_token = asegurar_token_valido(cuenta_id)
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token}"

    # Freno compartido con meli_http: si MeLi pidió esperar (429 / cabeceras de límite), todos esperan antes de volver a pedir
    meli_http.respetar_pausa()
    resp = meli_http.frenar_segun_cabeceras(requests.request(metodo, url, headers=headers, **kwargs))

    if resp.status_code == 401:
        access_token = refrescar_token_rechazado(cuenta_id, access_token)
        headers["Authorization"] = f"Bearer {access_token}"
        meli_http.respetar_pausa()
        resp = meli_http.frenar_segun_cabeceras(requests.request(metodo, url, headers=headers, **kwargs))

    return resp

"""
Flujo de OAuth 2.0 con Mercado Libre — Authorization Code flow.

El recorrido completo:
1. construir_url_autorizacion()  -> mandás al usuario a esta URL
2. MeLi lo redirige de vuelta a MELI_REDIRECT_URI con ?code=...&state=...
3. intercambiar_codigo_por_token(code) -> te da access_token + refresh_token
4. obtener_datos_usuario_meli(access_token) -> para saber QUIÉN te autorizó
   (su id numérico de MeLi, su nickname) y así crear/encontrar su cuenta
5. Cuando el access_token venga vencido, refrescar_token(refresh_token)
"""
import hmac
import secrets
import requests
import config

BASE_AUTH_URL = "https://auth.mercadolibre.com.ar/authorization"
BASE_API_URL = "https://api.mercadolibre.com"


def generar_state():
    """
    Token aleatorio de un solo uso para evitar ataques CSRF en el
    callback — se guarda en la sesión del navegador antes de mandar a
    MeLi, y se compara cuando vuelve.
    """
    return secrets.token_urlsafe(24)


def states_coinciden(recibido, esperado):
    """Compara el `state` que vuelve de Mercado Libre con el guardado, en tiempo constante y sin dar por buenos dos vacíos."""
    return bool(recibido) and bool(esperado) and hmac.compare_digest(str(recibido).encode(), str(esperado).encode())


def construir_url_autorizacion(state):
    return (
        f"{BASE_AUTH_URL}?response_type=code"
        f"&client_id={config.MELI_CLIENT_ID}"
        f"&redirect_uri={config.MELI_REDIRECT_URI}"
        f"&state={state}"
    )


def intercambiar_codigo_por_token(code):
    """
    Cambia el 'code' de la URL de vuelta por un access_token y
    refresh_token reales. Devuelve (ok: bool, datos_o_error).
    """
    try:
        resp = requests.post(
            f"{BASE_API_URL}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={
                "grant_type": "authorization_code",
                "client_id": config.MELI_CLIENT_ID,
                "client_secret": config.MELI_CLIENT_SECRET,
                "code": code,
                "redirect_uri": config.MELI_REDIRECT_URI,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return False, f"MeLi rechazó el intercambio de código: {resp.status_code} - {resp.text[:300]}"
        return True, resp.json()
    except Exception as e:
        return False, f"Error de conexión intercambiando el código: {e}"


def refrescar_token(refresh_token):
    """Igual que arriba, pero para renovar un access_token vencido."""
    try:
        resp = requests.post(
            f"{BASE_API_URL}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={
                "grant_type": "refresh_token",
                "client_id": config.MELI_CLIENT_ID,
                "client_secret": config.MELI_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return False, f"MeLi rechazó el refresh: {resp.status_code} - {resp.text[:300]}"
        return True, resp.json()
    except Exception as e:
        return False, f"Error de conexión refrescando el token: {e}"


def obtener_datos_usuario_meli(access_token):
    """
    Quién es el vendedor que acaba de autorizar — su id numérico de MeLi
    (la clave que usamos para no duplicar cuentas) y su nickname (para
    mostrar en la UI).
    """
    try:
        resp = requests.get(
            f"{BASE_API_URL}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return False, f"No se pudo consultar /users/me: {resp.status_code}"
        data = resp.json()
        return True, {
            "meli_user_id": data.get("id"),
            "nickname": data.get("nickname"),
            "email": data.get("email"),
            "site_id": data.get("site_id", config.MELI_SITE_ID),
        }
    except Exception as e:
        return False, f"Error de conexión consultando /users/me: {e}"

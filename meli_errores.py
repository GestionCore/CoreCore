"""
Cómo se le explica a una persona un rechazo de Mercado Libre. Nunca se muestra "403", un JSON ni el texto en inglés de la API: una frase que dice qué pasó y
qué hacer. El detalle técnico va al log.
"""

CAUSAS = {
    "item.title.not_modifiable": "Mercado Libre no deja cambiar el título de una publicación que ya tiene ventas.",
    "item.price.invalid": "Mercado Libre no aceptó ese precio.",
    "item.status.invalid": "Mercado Libre no deja pasar la publicación a ese estado ahora.",
}


# Mensajes de la API (en inglés) que se repiten y sí le sirven a la persona: se traducen en vez de mostrarlos tal cual o perder el motivo.
MENSAJES_CONOCIDOS = (
    ("no stock", "La publicación no tiene stock disponible: cargale unidades antes de reactivarla."),
    ("per variation", "Mercado Libre pide cambiar el precio de cada variante por separado: hacelo desde Mercado Libre."),
    ("variations", "Es una publicación con variantes y Mercado Libre no deja cambiarla así: hacelo desde Mercado Libre."),
)


def cuerpo_de(respuesta):
    """El JSON de una respuesta de requests como dict, o None si no se puede leer."""
    try:
        cuerpo = respuesta.json()
        return cuerpo if isinstance(cuerpo, dict) else None
    except Exception:
        return None


def explicar_error_meli(codigo, cuerpo):
    """Una frase para la persona a partir de la respuesta de Mercado Libre (cuerpo = dict ya decodificado, o None)."""
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    print(f"[MeLi] rechazo {codigo}: {str(cuerpo)[:300]}")
    for causa in cuerpo.get("cause") or []:
        if isinstance(causa, dict) and causa.get("code") in CAUSAS:
            return CAUSAS[causa["code"]]
    mensaje = str(cuerpo.get("message") or "").lower()
    for fragmento, frase in MENSAJES_CONOCIDOS:
        if fragmento in mensaje:
            return frase
    if codigo in (401, 403):
        return "Mercado Libre no autorizó el cambio. Probá reconectar tu cuenta."
    if codigo == 404:
        return "Mercado Libre no encontró esa publicación: puede que esté cerrada o eliminada."
    if codigo == 409:
        return "La publicación cambió en Mercado Libre mientras tanto. Recargá la pantalla y probá de nuevo."
    if codigo == 429:
        return "Mercado Libre pidió esperar un momento. Probá de nuevo en un minuto."
    if codigo and codigo >= 500:
        return "Mercado Libre no respondió bien. Probá de nuevo en unos minutos."
    for causa in cuerpo.get("cause") or []:
        if isinstance(causa, dict) and causa.get("message"):
            return f"Mercado Libre no aceptó el cambio: {str(causa['message'])[:140]}"
    return "Mercado Libre no aceptó el cambio. No se modificó nada."


def explicar_respuesta(respuesta):
    return explicar_error_meli(getattr(respuesta, "status_code", None), cuerpo_de(respuesta))


SIN_CONEXION = "No se pudo conectar con Mercado Libre. Probá de nuevo en un momento."

"""
Cómo se le explica a una persona un rechazo de Mercado Libre. Nunca se muestra "403", un JSON ni el texto en inglés de la API: una frase que dice qué pasó y
qué hacer. El detalle técnico va al log.
"""
import re

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


# Nombres de los atributos que Mercado Libre suele exigir, tal como los informa (en mayúsculas o en minúsculas) → cómo se los llama una persona.
ATRIBUTOS = {
    "brand": "Marca", "model": "Modelo", "gtin": "Código universal (GTIN/EAN)", "mpn": "Código de fabricante", "color": "Color", "main_color": "Color", "size": "Talle",
    "gender": "Género", "family_name": "Nombre de familia", "seller_sku": "SKU", "item_condition": "Condición", "age_group": "Grupo de edad",
}
FRASE_ATRIBUTOS = "Mercado Libre no deja guardar el cambio: faltan datos obligatorios en la publicación{detalle}. Editalos desde Mercado Libre primero."


def atributos_faltantes(cuerpo):
    """
    None si el rechazo no es por datos obligatorios que faltan; si lo es, la lista (puede estar vacía) de cómo se llaman los que faltan.
    Forma REAL verificada (POST /items/validate, 2026-10-07): {"error": "validation_error", "status": 400, "cause": [{"code": "body.required_fields",
    "references": ["body"], "message": "The body does not contains some or none of the following properties [family_name]"}]}. También se reconocen los códigos
    de atributos obligatorios que documenta Mercado Libre (`item.attributes.*` con «missing»/«required»): ese caso no se pudo provocar sin escribir en una cuenta real.
    Un `validation_error` suelto NO alcanza: hay muchos otros errores de validación (precio, título…) y decir «faltan atributos» sería mentir.
    """
    causas = [c for c in (cuerpo or {}).get("cause") or [] if isinstance(c, dict)] if isinstance(cuerpo, dict) else []
    nombres, es_de_atributos = [], False
    for c in causas:
        codigo, mensaje = str(c.get("code") or "").lower(), str(c.get("message") or "")
        referencias = " ".join(str(r) for r in (c.get("references") or []))
        pide = any(x in codigo or x in mensaje.lower() for x in ("missing", "required"))
        if codigo == "body.required_fields" or ("attributes" in codigo and pide) or ("item.attributes" in referencias and pide):
            es_de_atributos = True
            for grupo in re.findall(r"\[([^\]]+)\]", mensaje):
                nombres += [n.strip() for n in grupo.split(",") if n.strip()]
            nombres += re.findall(r"item\.attributes\.([A-Za-z_]+)", referencias)
    if not es_de_atributos:
        return None
    vistos, lista = set(), []
    for n in nombres:
        legible = ATRIBUTOS.get(n.lower(), n)
        if legible not in vistos:
            vistos.add(legible)
            lista.append(legible)
    return lista


def frase_de_atributos(nombres):
    return FRASE_ATRIBUTOS.format(detalle=f" ({', '.join(nombres[:5])})" if nombres else " (marca, modelo, código…)")


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
    if codigo == 400:
        faltan = atributos_faltantes(cuerpo)
        if faltan is not None:
            return frase_de_atributos(faltan)
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

"""
Edición de una publicación desde el panel lateral: qué se le manda a Mercado Libre y cómo se explica un rechazo.

Reglas (cada una nació de un problema real):
  · Solo se manda lo que CAMBIÓ. Antes iban título, precio y estado juntos siempre, y con una publicación que ya tiene ventas MeLi no deja tocar el
    título: rechazaba también el precio, que era lo único que la persona había cambiado.
  · "Finalizar" (status closed) no se ofrece: en Mercado Libre no tiene vuelta atrás y estaba a un clic, sin confirmación. Se hace desde MeLi.
  · Nada se guarda en CoreLux hasta que Mercado Libre lo acepta: antes quedaba un precio o un título que no eran los reales.
"""

from meli_errores import explicar_error_meli  # noqa: F401  (se re-exporta: el panel y las pruebas lo piden acá)

ESTADOS_EDITABLES = ("active", "paused")
MAX_TITULO = 120      # tope amplio: el límite real depende de la categoría (los títulos de ropa de la cuenta de prueba tienen 79-98) y lo decide Mercado Libre
NOMBRES_ESTADO = {
    "active": "Activa", "paused": "Pausada", "closed": "Finalizada en Mercado Libre", "under_review": "En revisión de Mercado Libre",
    "inactive": "Inactiva", "payment_required": "Pendiente de pago", "not_yet_active": "Todavía no activa",
}

def nombre_estado(estado):
    return NOMBRES_ESTADO.get(estado, (estado or "Sin estado").replace("_", " ").capitalize())


def _a_numero(valor):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def armar_cambios(actual, pedido):
    """
    actual = {"titulo", "precio", "estado"} como están en CoreLux; pedido = lo que mandó el formulario (None = no tocar).
    Devuelve (payload para Mercado Libre, lista de errores). Con errores no se manda nada.
    """
    payload, errores = {}, []

    titulo = pedido.get("titulo")
    if titulo is not None:
        titulo = " ".join(str(titulo).split())
        if titulo != (actual.get("titulo") or ""):
            if not titulo:
                errores.append("El título no puede quedar vacío.")
            elif len(titulo) > MAX_TITULO:
                errores.append(f"El título no puede pasar de {MAX_TITULO} caracteres (tiene {len(titulo)}).")
            else:
                payload["title"] = titulo

    if pedido.get("precio") not in (None, ""):
        precio = _a_numero(pedido["precio"])
        if precio is None or precio <= 0:
            errores.append("El precio tiene que ser un número mayor a cero.")
        elif abs(precio - float(actual.get("precio") or 0)) > 0.004:
            payload["price"] = round(precio, 2)

    estado = pedido.get("estado")
    if estado and estado != actual.get("estado"):
        if estado not in ESTADOS_EDITABLES:
            errores.append("Desde acá solo se puede activar o pausar. Para finalizar una publicación hacelo en Mercado Libre.")
        elif actual.get("estado") not in ESTADOS_EDITABLES:
            errores.append(f"La publicación está «{nombre_estado(actual.get('estado'))}»: no se puede cambiar su estado desde acá.")
        else:
            payload["status"] = estado

    return payload, errores


def resumen_cambios(actual, payload):
    """Lista de textos legibles de lo que se va a cambiar (para la respuesta y la auditoría)."""
    lineas = []
    if "title" in payload:
        lineas.append(f"Título: «{actual.get('titulo')}» → «{payload['title']}»")
    if "price" in payload:
        lineas.append(f"Precio: ${float(actual.get('precio') or 0):,.0f} → ${payload['price']:,.0f}".replace(",", "."))
    if "status" in payload:
        lineas.append(f"Estado: {nombre_estado(actual.get('estado'))} → {nombre_estado(payload['status'])}")
    return lineas

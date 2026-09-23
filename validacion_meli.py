"""
Extracción segura de campos de las respuestas de la API de MeLi. Varios
bugs de esta semana salieron de asumir que un campo siempre iba a estar
ahí con el tipo esperado (shipping.logistic_type, tags, etc.) — cuando
faltaba o venía distinto, tronaba con un KeyError/TypeError críptico a
mitad de una sincronización completa. Esto cambia eso por un aviso claro
y un valor por defecto, sin cortar todo lo demás que sí se pudo procesar.
"""


def campo_seguro(diccionario, ruta, default=None, tipo_esperado=None, contexto=""):
    """
    Extrae un campo anidado usando "a.b.c" como ruta (ej: "shipping.logistic_type").
    Si falta, o no es del tipo esperado, devuelve default y avisa por
    consola en vez de romper el flujo que lo llamó.
    """
    valor = diccionario
    try:
        for parte in ruta.split("."):
            if isinstance(valor, dict):
                valor = valor.get(parte)
            else:
                valor = None
                break
    except Exception:
        valor = None

    if valor is None:
        return default

    if tipo_esperado and not isinstance(valor, tipo_esperado):
        etiqueta_contexto = f" en {contexto}" if contexto else ""
        print(f"[Validación] ⚠️ Campo '{ruta}' vino con tipo inesperado "
              f"({type(valor).__name__}, se esperaba {tipo_esperado.__name__}){etiqueta_contexto} — usando default: {default!r}")
        return default

    return valor

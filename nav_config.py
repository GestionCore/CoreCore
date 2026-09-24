"""
Fuente única de verdad para la navegación agrupada de CoreLux.

Estos 3 grupos (catalogo / finanzas / crecimiento) ya existían como
dropdowns en el navbar — acá se centralizan para que también alimenten
el tab-strip persistente (base.html) y el tracking de "más usado"
(app.py + auth/middleware.py) sin tener la misma lista pegada en tres
lugares distintos y desincronizarse con el tiempo.

Si se agrega una página nueva a un grupo: se agrega ACÁ, y el menú, el
tab-strip y el tracking la reconocen solos.
"""

GRUPOS_NAV = {
    "catalogo": {
        "label": "Catálogo",
        "paginas": [
            {"nav_key": "stock", "label": "Stock", "href": "/", "endpoint": "landing"},
            {"nav_key": "stock_masivo", "label": "Stock Masivo", "href": "/stock_masivo", "endpoint": "stock_masivo_vista"},
            {"nav_key": "despacho", "label": "Despacho", "href": "/despacho", "endpoint": "despacho_vista"},
            {"nav_key": "preguntas", "label": "Preguntas", "href": "/preguntas", "endpoint": "preguntas_vista"},
        ],
    },
    "finanzas": {
        "label": "Finanzas",
        "paginas": [
            {"nav_key": "metricas", "label": "Ganancia Real", "href": "/metricas", "endpoint": "metricas_vista"},
            {"nav_key": "facturacion", "label": "Facturación", "href": "/facturacion", "endpoint": "facturacion_vista"},
            {"nav_key": "costos", "label": "Costos", "href": "/costos", "endpoint": "costos_vista"},
            {"nav_key": "ventas_manuales", "label": "Ventas fuera de MeLi", "href": "/ventas_manuales", "endpoint": "ventas_manuales_vista"},
            {"nav_key": "historial_precios", "label": "Historial de Precios", "href": "/historial_precios", "endpoint": "historial_precios_vista"},
            {"nav_key": "calculadora", "label": "Calculadora MeLi", "href": "/calculadora", "endpoint": "calculadora_vista"},
            {"nav_key": "reporte_fiscal", "label": "Reporte Fiscal", "href": "/reporte_fiscal", "endpoint": "reporte_fiscal_vista"},
        ],
    },
    "crecimiento": {
        "label": "Crecimiento",
        "paginas": [
            {"nav_key": "promociones", "label": "Promociones", "href": "/promociones", "endpoint": "promociones_vista"},
            {"nav_key": "tendencias", "label": "Tendencias", "href": "/tendencias", "endpoint": "tendencias_vista"},
            {"nav_key": "competencia", "label": "Espía de Competencia", "href": "/competencia", "endpoint": "competencia_vista"},
            {"nav_key": "embudo_conversion", "label": "Embudo de Conversión", "href": "/embudo_conversion", "endpoint": "embudo_conversion_vista"},
            {"nav_key": "reputacion", "label": "Reputación", "href": "/reputacion", "endpoint": "reputacion_vista"},
            {"nav_key": "publicidad", "label": "Publicidad", "href": "/publicidad", "endpoint": "publicidad_vista"},
            {"nav_key": "logros", "label": "Logros", "href": "/logros", "endpoint": "logros_vista"},
        ],
    },
}

# endpoint (nombre de función Flask) -> (grupo, nav_key) — para trackear
# visitas reales en app.py sin duplicar la lista de arriba.
ENDPOINT_A_NAV = {
    item["endpoint"]: (grupo, item["nav_key"])
    for grupo, datos in GRUPOS_NAV.items()
    for item in datos["paginas"]
}

# Piso mínimo de visitas antes de mostrar el badge "MÁS USADO" — evita
# marcar una sección al azar después de un solo click.
UMBRAL_MAS_USADO = 3


def calcular_mas_usado(contadores_por_nav_key):
    """
    contadores_por_nav_key: dict {nav_key: contador} (de navegacion_visitas).
    Devuelve dict {grupo: nav_key} con la sección más visitada de cada
    grupo, solo si superó UMBRAL_MAS_USADO.
    """
    resultado = {}
    for grupo, datos in GRUPOS_NAV.items():
        mejor_key, mejor_contador = None, 0
        for item in datos["paginas"]:
            c = contadores_por_nav_key.get(item["nav_key"], 0)
            if c > mejor_contador:
                mejor_key, mejor_contador = item["nav_key"], c
        if mejor_key and mejor_contador >= UMBRAL_MAS_USADO:
            resultado[grupo] = mejor_key
    return resultado

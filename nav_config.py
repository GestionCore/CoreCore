"""
Fuente única de verdad de la navegación de CoreLux.

El menú lateral muestra las SECCIONES (siete, siempre a la vista) y, dentro de cada sección, las pantallas aparecen como pestañas arriba de la
página. Antes eran 3 desplegables + una franja de pestañas + 22 pantallas sueltas: para llegar a algo había que saber en cuál de los grupos estaba.

Si se agrega una pantalla: se agrega ACÁ (en la sección que corresponda) y el menú, las pestañas, el seguimiento de "más usado" y el buscador la
reconocen solos. `active_nav` de cada plantilla es el `nav_key` de su pantalla.
"""

GRUPOS_NAV = {
    "inicio": {
        "label": "Inicio", "icono": "home",
        "paginas": [
            {"nav_key": "dashboard", "label": "Dashboard", "href": "/dashboard", "endpoint": "dashboard_personalizable"},
        ],
    },
    "dia": {
        "label": "Día a día", "icono": "bolt",
        "paginas": [
            {"nav_key": "despacho", "label": "Despacho", "href": "/despacho", "endpoint": "despacho_vista"},
            {"nav_key": "preguntas", "label": "Preguntas", "href": "/preguntas", "endpoint": "preguntas_vista"},
            {"nav_key": "logros", "label": "Pendientes", "href": "/logros", "endpoint": "logros_vista"},
            {"nav_key": "reputacion", "label": "Reputación", "href": "/reputacion", "endpoint": "reputacion_vista"},
        ],
    },
    "ventas": {
        "label": "Ventas y ganancia", "icono": "coin",
        "paginas": [
            {"nav_key": "metricas", "label": "Ganancia Real", "href": "/metricas", "endpoint": "metricas_vista"},
            {"nav_key": "facturacion", "label": "Facturación", "href": "/facturacion", "endpoint": "facturacion_vista"},
            {"nav_key": "cobros", "label": "Cobros", "href": "/cobros", "endpoint": "cobros_vista"},
            {"nav_key": "ventas_manuales", "label": "Ventas fuera de MeLi", "href": "/ventas_manuales", "endpoint": "ventas_manuales_vista"},
            {"nav_key": "reporte_fiscal", "label": "Reporte Fiscal", "href": "/reporte_fiscal", "endpoint": "reporte_fiscal_vista"},
            {"nav_key": "monotributo", "label": "Monotributo", "href": "/monotributo", "endpoint": "monotributo_vista", "requiere": "monotributo"},
        ],
    },
    "precios": {
        "label": "Precios y costos", "icono": "tag",
        "paginas": [
            {"nav_key": "costos", "label": "Costos", "href": "/costos", "endpoint": "costos_vista"},
            {"nav_key": "precios", "label": "Precios", "href": "/precios", "endpoint": "precios_vista"},
            {"nav_key": "calculadora", "label": "Calculadora MeLi", "href": "/calculadora", "endpoint": "calculadora_vista"},
            {"nav_key": "historial_precios", "label": "Historial de Precios", "href": "/historial_precios", "endpoint": "historial_precios_vista"},
        ],
    },
    "stock": {
        "label": "Stock", "icono": "package",
        "paginas": [
            {"nav_key": "stock", "label": "Stock", "href": "/stock", "endpoint": "stock_vista"},
            {"nav_key": "stock_masivo", "label": "Stock Masivo", "href": "/stock_masivo", "endpoint": "stock_masivo_vista"},
        ],
    },
    "publicaciones": {
        "label": "Publicaciones", "icono": "star",
        "paginas": [
            {"nav_key": "calidad", "label": "Calidad", "href": "/calidad", "endpoint": "calidad_vista"},
            {"nav_key": "opiniones", "label": "Opiniones", "href": "/opiniones", "endpoint": "opiniones_vista"},
            {"nav_key": "embudo_conversion", "label": "Embudo de Conversión", "href": "/embudo_conversion", "endpoint": "embudo_conversion_vista"},
        ],
    },
    "crecimiento": {
        "label": "Crecimiento", "icono": "trend",
        "paginas": [
            {"nav_key": "promociones", "label": "Promociones", "href": "/promociones", "endpoint": "promociones_vista"},
            {"nav_key": "publicidad", "label": "Publicidad", "href": "/publicidad", "endpoint": "publicidad_vista", "requiere": "ads"},
            {"nav_key": "tendencias", "label": "Tendencias", "href": "/tendencias", "endpoint": "tendencias_vista"},
            {"nav_key": "competencia", "label": "Competencia", "href": "/competencia", "endpoint": "competencia_vista", "requiere": "catalogo"},
        ],
    },
}

# endpoint (nombre de función Flask) -> (sección, nav_key) — para trackear visitas reales sin duplicar la lista de arriba.
ENDPOINT_A_NAV = {
    item["endpoint"]: (grupo, item["nav_key"])
    for grupo, datos in GRUPOS_NAV.items()
    for item in datos["paginas"]
}

# nav_key -> sección (para marcar en el menú lateral la sección de la pantalla actual)
SECCION_DE_NAV = {item["nav_key"]: grupo for grupo, datos in GRUPOS_NAV.items() for item in datos["paginas"]}
# Pantallas que no están en el menú pero pertenecen a una sección (se llega por un link, el buscador o un botón)
SECCION_DE_NAV.update({"comparador_logistica": "ventas", "timeline_publicacion": "stock"})

# Piso mínimo de visitas antes de mostrar el badge "MÁS USADO" — evita marcar una sección al azar después de un solo click.
UMBRAL_MAS_USADO = 3


def calcular_mas_usado(contadores_por_nav_key):
    """
    contadores_por_nav_key: dict {nav_key: contador} (de navegacion_visitas).
    Devuelve dict {sección: nav_key} con la pantalla más visitada de cada sección, solo si superó UMBRAL_MAS_USADO.
    """
    resultado = {}
    for grupo, datos in GRUPOS_NAV.items():
        if len(datos["paginas"]) < 2:
            continue                      # con una sola pantalla no hay nada que destacar
        mejor_key, mejor_contador = None, 0
        for item in datos["paginas"]:
            c = contadores_por_nav_key.get(item["nav_key"], 0)
            if c > mejor_contador:
                mejor_key, mejor_contador = item["nav_key"], c
        if mejor_key and mejor_contador >= UMBRAL_MAS_USADO:
            resultado[grupo] = mejor_key
    return resultado

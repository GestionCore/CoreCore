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
        # una sola pantalla con cinco partes (las pestañas saltan a cada una): no hay una «más usada» que destacar
        "una_pantalla": True,
        "paginas": [
            {"nav_key": "despacho", "label": "Despacho", "href": "/dia", "ancla": "despacho", "endpoint": "dia_vista"},
            {"nav_key": "preguntas", "label": "Preguntas", "href": "/dia", "ancla": "preguntas", "endpoint": "dia_vista"},
            {"nav_key": "reclamos", "label": "Reclamos", "href": "/dia", "ancla": "reclamos", "endpoint": "dia_vista"},
            {"nav_key": "logros", "label": "Pendientes", "href": "/dia", "ancla": "pendientes", "endpoint": "dia_vista"},
            {"nav_key": "reputacion", "label": "Reputación", "href": "/dia", "ancla": "reputacion", "endpoint": "dia_vista"},
        ],
    },
    # Lo de hoy en una sola pantalla (ventas por hora, visitas, conversión y publicidad, todo en neto): una sección de una pantalla, igual que la Calculadora
    "monitor_en_vivo": {
        "label": "Monitor en vivo", "icono": "pulse",
        "paginas": [
            {"nav_key": "monitor_en_vivo", "label": "Monitor en vivo", "href": "/monitor_en_vivo", "endpoint": "monitor_en_vivo_vista"},
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
            {"nav_key": "historial_precios", "label": "Historial de Precios", "href": "/historial_precios", "endpoint": "historial_precios_vista"},
        ],
    },
    # Pantalla suelta: se usa todos los días y antes estaba escondida como pestaña de «Precios y costos». Una sección de una sola pantalla no lleva pestañas.
    "calculadora": {
        "label": "Calculadora", "icono": "calculator",
        "paginas": [
            {"nav_key": "calculadora", "label": "Calculadora", "href": "/calculadora", "endpoint": "calculadora_vista"},
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
            {"nav_key": "mercado", "label": "Radar", "href": "/mercado", "endpoint": "mercado_vista"},
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
SECCION_DE_NAV.update({"timeline_publicacion": "stock"})

# El badge "MÁS USADO" solo aparece cuando hay uso real de ESA persona que lo respalde: antes se marcaba la pantalla más visitada de cada sección apenas pasaba de 3 visitas,
# y con poco uso (o con dos pantallas casi empatadas) era ruido. Ahora hace falta que la sección tenga al menos VISITAS_MINIMAS_SECCION visitas en total y que la
# favorita se lleve al menos PROPORCION_MAS_USADO de ellas (una preferencia clara, no un empate).
VISITAS_MINIMAS_SECCION = 10
PROPORCION_MAS_USADO = 0.6


def calcular_mas_usado(contadores_por_nav_key):
    """
    contadores_por_nav_key: dict {nav_key: contador} (de navegacion_visitas, de UNA persona).
    Devuelve dict {sección: nav_key} con la pantalla favorita de cada sección, solo si hay datos suficientes y una preferencia clara.
    """
    resultado = {}
    for grupo, datos in GRUPOS_NAV.items():
        if len(datos["paginas"]) < 2 or datos.get("una_pantalla"):
            continue                      # con una sola pantalla no hay nada que destacar
        visitas = {item["nav_key"]: contadores_por_nav_key.get(item["nav_key"], 0) for item in datos["paginas"]}
        total = sum(visitas.values())
        if total < VISITAS_MINIMAS_SECCION:
            continue                      # todavía no hay datos
        mejor_key = max(visitas, key=visitas.get)
        if visitas[mejor_key] / total >= PROPORCION_MAS_USADO:
            resultado[grupo] = mejor_key
    return resultado

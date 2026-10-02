"""
Análisis de categoría de Monotributo — compara la facturación real
(últimos 12 meses, de la propia base de ventas) contra las escalas
vigentes de AFIP, y avisa si conviene recategorizarse.

IMPORTANTE — mantenimiento: estos montos los actualiza AFIP dos veces
por año (típicamente en enero y julio, aunque en 2026 hubo un ajuste
extra en agosto). ESCALAS_VIGENTES_DESDE queda documentado a propósito
para que quien lo revise en el futuro sepa que hay que chequear si
todavía es la tabla correcta — no es algo para "cargar una vez y
olvidarse".

La proyección de si va a cruzar de categoría usa el RITMO DE VENTA
PROPIO del usuario (creciendo o cayendo), no una predicción de demanda
de mercado externo — eso es un feature más grande y separado, todavía
no construido.

Esto nunca le dice al usuario "hacé tal cosa" con total seguridad —
solo avisa y sugiere confirmar con un contador antes de recategorizarse,
como corresponde para algo con implicancia fiscal real.
"""
from datetime import datetime, timedelta
import db

ESCALAS_VIGENTES_DESDE = "2026-08-01"

# Venta de cosas muebles — la actividad de este negocio (indumentaria).
# Categorías I/J/K también sirven para servicios desde 2026, pero acá
# solo importa la columna de bienes.
ESCALAS = [
    {"categoria": "A", "tope_anual": 12009410.45, "cuota_mensual": 49527.18},
    {"categoria": "B", "tope_anual": 17595182.74, "cuota_mensual": 56379.08},
    {"categoria": "C", "tope_anual": 24670494.31, "cuota_mensual": 64530.58},
    {"categoria": "D", "tope_anual": 30628651.43, "cuota_mensual": 82564.81},
    {"categoria": "E", "tope_anual": 36028231.33, "cuota_mensual": 108267.51},
    {"categoria": "F", "tope_anual": 45151659.41, "cuota_mensual": 129930.65},
    {"categoria": "G", "tope_anual": 53995798.87, "cuota_mensual": 158815.05},
    {"categoria": "H", "tope_anual": 81924660.37, "cuota_mensual": 317895.01},
]
PRECIO_UNITARIO_MAXIMO = 716840.77

MESES_VENTANA_RECATEGORIZACION = {1: "enero", 7: "julio"}  # AFIP recategoriza cada enero y julio


def _categoria_para_facturacion(facturacion_anual):
    for escala in ESCALAS:
        if facturacion_anual <= escala["tope_anual"]:
            return escala
    return None  # por encima de la H — ya no aplica monotributo, es Responsable Inscripto


def _indice_categoria(letra):
    for i, e in enumerate(ESCALAS):
        if e["categoria"] == letra:
            return i
    return None


def _proxima_ventana_recategorizacion(hoy):
    for año_offset in (0, 1):
        for mes in (1, 7):
            candidata = datetime(hoy.year + año_offset, mes, 1)
            if candidata > hoy:
                return candidata
    return datetime(hoy.year + 1, 1, 1)


def evaluar_categoria(usuario_id, cuenta_id):
    hoy = datetime.now()
    hace_12_meses = (hoy - timedelta(days=365)).strftime("%Y-%m-%d")
    hoy_str = hoy.strftime("%Y-%m-%d")
    hace_3_meses = (hoy - timedelta(days=90)).strftime("%Y-%m-%d")
    hace_6_meses = (hoy - timedelta(days=180)).strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_12_meses, hoy_str))
        facturacion_12m = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_3_meses, hoy_str))
        facturacion_ultimos_3m = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_6_meses, hace_3_meses))
        facturacion_3m_anteriores = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT MAX(precio_venta) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (hace_12_meses, hoy_str))
        precio_maximo_vendido = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT categoria_monotributo FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
        categoria_declarada = fila[0] if fila else None

    categoria_real = _categoria_para_facturacion(facturacion_12m)
    idx_real = _indice_categoria(categoria_real["categoria"]) if categoria_real else None
    idx_declarada = _indice_categoria(categoria_declarada) if categoria_declarada else None

    variacion_pct = None
    if facturacion_3m_anteriores > 0:
        variacion_pct = round(((facturacion_ultimos_3m - facturacion_3m_anteriores) / facturacion_3m_anteriores) * 100, 1)

    meses_para_cruzar = None
    if categoria_declarada and idx_declarada is not None and variacion_pct and variacion_pct > 0:
        escala_declarada = ESCALAS[idx_declarada]
        margen_restante = escala_declarada["tope_anual"] - facturacion_12m
        crecimiento_mensual_absoluto = (facturacion_ultimos_3m / 3) * (variacion_pct / 100)
        if margen_restante > 0 and crecimiento_mensual_absoluto > 0:
            meses_para_cruzar = round(margen_restante / crecimiento_mensual_absoluto, 1)

    alertas = []

    if categoria_declarada and idx_real is not None and idx_declarada is not None:
        if idx_real > idx_declarada:
            alertas.append({
                "tipo": "urgente",
                "texto": f"Tu facturación real de los últimos 12 meses te ubica en Categoría {categoria_real['categoria']}, pero tenés declarada la {categoria_declarada}. Convendría recategorizarte cuanto antes — estar por debajo de tu categoría real tiene consecuencias con AFIP."
            })
        elif idx_real < idx_declarada:
            escala_actual = ESCALAS[idx_declarada]
            porcentaje_uso = round((facturacion_12m / escala_actual["tope_anual"]) * 100, 1)
            if porcentaje_uso < 60:
                alertas.append({
                    "tipo": "oportunidad",
                    "texto": f"Estás usando el {porcentaje_uso}% del techo de tu categoría declarada ({categoria_declarada}). Facturando lo que facturás, la Categoría {categoria_real['categoria']} te alcanzaría — bajar podría significar pagar menos cuota mensual."
                })
    elif categoria_declarada and idx_declarada is not None:
        escala_actual = ESCALAS[idx_declarada]
        porcentaje_uso = round((facturacion_12m / escala_actual["tope_anual"]) * 100, 1)
        if porcentaje_uso >= 85:
            alertas.append({
                "tipo": "importante",
                "texto": f"Estás usando el {porcentaje_uso}% del techo de tu categoría ({categoria_declarada}). Falta poco para necesitar recategorizarte a la próxima."
            })

    if meses_para_cruzar is not None and meses_para_cruzar <= 6:
        proxima_ventana = _proxima_ventana_recategorizacion(hoy)
        meses_hasta_ventana = round((proxima_ventana - hoy).days / 30, 1)
        if meses_para_cruzar < meses_hasta_ventana:
            alertas.append({
                "tipo": "proyeccion",
                "texto": f"Al ritmo de crecimiento de tus últimas ventas, podrías superar el techo de tu categoría en unos {meses_para_cruzar} mes(es) — antes de la próxima ventana de recategorización de AFIP ({MESES_VENTANA_RECATEGORIZACION[proxima_ventana.month]} {proxima_ventana.year}). Vale la pena tenerlo en el radar."
            })

    if precio_maximo_vendido > PRECIO_UNITARIO_MAXIMO:
        alertas.append({
            "tipo": "urgente",
            "texto": f"Vendiste al menos un artículo a ${precio_maximo_vendido:,.2f}, por encima del precio unitario máximo permitido en monotributo (${PRECIO_UNITARIO_MAXIMO:,.2f}). Esto podría requerir pasarte a Responsable Inscripto — confirmalo con tu contador."
        })

    if categoria_real is None:
        alertas.append({
            "tipo": "urgente",
            "texto": "Tu facturación de los últimos 12 meses superó el techo máximo de todas las categorías de monotributo — es momento de evaluar el paso a Responsable Inscripto con tu contador."
        })

    return {
        "facturacion_12m": facturacion_12m,
        "categoria_real": categoria_real["categoria"] if categoria_real else None,
        "categoria_declarada": categoria_declarada,
        "cuota_mensual_declarada": ESCALAS[idx_declarada]["cuota_mensual"] if idx_declarada is not None else None,
        "tope_categoria_declarada": ESCALAS[idx_declarada]["tope_anual"] if idx_declarada is not None else None,
        "variacion_pct_propia": variacion_pct,
        "meses_para_cruzar": meses_para_cruzar,
        "alertas": alertas,
        "escalas": ESCALAS,
        "vigente_desde": ESCALAS_VIGENTES_DESDE,
    }


def guardar_categoria_declarada(usuario_id, cuenta_id, categoria):
    if categoria and _indice_categoria(categoria) is None:
        return False
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE cuentas_meli SET categoria_monotributo = %s WHERE id = %s", (categoria or None, cuenta_id))
    return True

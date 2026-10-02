"""
Análisis de stock — portado de Santi Mens. La detección en sí (qué está
en riesgo, dónde se rompió la curva de talles) es idéntica; lo que
cambia es de dónde sale el cursor (una conexión con RLS activo, ver
db.conexion_usuario) y el join de variantes, que ahora apunta a
productos_padre.id (la clave propia) en vez de id_meli.

Los "..._y_alertar" del original (que mandaban el aviso por WhatsApp)
todavía no se portaron — CoreLux no tiene el puente de WhatsApp
conectado por ahora. Lo que sí está acá es la detección pura, que es lo
que consumen las páginas y APIs del dashboard.
"""
import re
from datetime import timedelta
from utils import extraer_talle, hoy_argentina

VENTANA_DIAS = 14
UMBRAL_DIAS_RESTANTES = 5
CENTRALES = {"M", "L", "XL"}


def obtener_variantes_en_riesgo(cursor, umbral_dias=UMBRAL_DIAS_RESTANTES, ventana_dias=VENTANA_DIAS):
    fecha_hasta = hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = (hoy_argentina() - timedelta(days=ventana_dias)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT v.id_variante, v.talle, v.color, v.stock_propio, v.stock_full, p.titulo, p.id_meli,
               pr.nombre, pr.tiempo_entrega_dias
        FROM productos_variantes v
        JOIN productos_padre p ON p.id = v.id_padre
        LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
    """)
    variantes = cursor.fetchall()

    cursor.execute("""
        SELECT id_variante, SUM(cantidad) FROM ventas WHERE fecha_venta BETWEEN %s AND %s GROUP BY id_variante
    """, (fecha_desde, fecha_hasta))
    unidades_por_variante = dict(cursor.fetchall())

    en_riesgo = []
    for id_variante, talle, color, stock_propio, stock_full, titulo, id_meli, proveedor_nombre, tiempo_entrega in variantes:
        stock_total = (stock_propio or 0) + (stock_full or 0)
        unidades_vendidas = unidades_por_variante.get(id_variante, 0)
        if unidades_vendidas <= 0:
            continue
        velocidad_diaria = unidades_vendidas / ventana_dias
        if velocidad_diaria <= 0:
            continue
        dias_restantes = stock_total / velocidad_diaria

        dias_para_pedir = None
        pedir_ya = False
        if tiempo_entrega is not None:
            dias_para_pedir = round(dias_restantes - tiempo_entrega, 1)
            pedir_ya = dias_para_pedir <= 0

        umbral_efectivo = umbral_dias if tiempo_entrega is None else max(umbral_dias, tiempo_entrega)
        if dias_restantes <= umbral_efectivo:
            en_riesgo.append({
                "id_variante": id_variante, "id_meli": id_meli, "titulo": titulo, "talle": talle, "color": color,
                "stock_total": stock_total, "velocidad_diaria": round(velocidad_diaria, 1), "dias_restantes": round(dias_restantes, 1),
                "proveedor_nombre": proveedor_nombre, "tiempo_entrega_dias": tiempo_entrega,
                "dias_para_pedir": dias_para_pedir, "pedir_ya": pedir_ya
            })

    en_riesgo.sort(key=lambda x: x["dias_restantes"])
    return en_riesgo


def _limpiar_titulo_modelo_local(titulo):
    t = re.sub(r'\b(talle|size)\s*[:#]?\s*(xxxl|xxl|xl|l|m|s|\d+)\b', '', titulo, flags=re.IGNORECASE)
    t = re.sub(r'\b(xxxl|xxl|xl|l|m|s)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def evaluar_curva_talles(cursor):
    """
    Detecta modelos activos donde los talles centrales (M, L, XL) están
    casi agotados (<=2 u.) mientras los extremos todavía tienen stock —
    señal de quiebre parcial que puede perjudicar el posicionamiento en
    Cassini.

    Mejora real respecto al original: la versión de Santi Mens derivaba
    el talle re-buscando un patrón (M/L/XL/...) DENTRO DEL TÍTULO de la
    publicación — pero cuando una sola publicación tiene varias
    variantes de talle debajo (un solo id_meli, varios v.talle), todas
    esas filas comparten el mismo título, así que la búsqueda por texto
    siempre daba el mismo resultado para todas y nunca detectaba una
    curva rota real en ese caso. Ahora usa el talle real de la variante
    (v.talle), y solo cae al patrón de texto como respaldo si esa
    columna viene vacía.
    """
    cursor.execute("""
        SELECT p.id_meli, p.titulo, v.talle,
               COALESCE(v.stock_propio,0)+COALESCE(v.stock_full,0) as stock_total
        FROM productos_padre p JOIN productos_variantes v ON v.id_padre = p.id
        WHERE p.estado = 'active'
    """)
    filas = cursor.fetchall()

    modelos = {}
    for id_meli, titulo, talle_variante, stock_total in filas:
        clave = _limpiar_titulo_modelo_local(titulo)
        talle = extraer_talle(titulo, talle_variante)
        if clave not in modelos:
            modelos[clave] = {"titulo": clave, "talles": {}, "id_referencia": id_meli}
        modelos[clave]["talles"][talle] = modelos[clave]["talles"].get(talle, 0) + stock_total

    en_riesgo = []
    for clave, data in modelos.items():
        talles = data["talles"]
        centrales = {t: s for t, s in talles.items() if t in CENTRALES}
        extremos = {t: s for t, s in talles.items() if t not in CENTRALES and t != "Único"}
        if not centrales or not extremos:
            continue
        centrales_bajos = [t for t, s in centrales.items() if s <= 2]
        extremos_con_stock = any(s > 2 for s in extremos.values())
        if centrales_bajos and extremos_con_stock:
            en_riesgo.append({"modelo": clave, "id_referencia": data["id_referencia"], "talles_escasos": centrales_bajos})

    return en_riesgo

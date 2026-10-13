"""
Análisis de stock — portado de Santi Mens. La detección de qué está en
riesgo es idéntica; lo que cambia es de dónde sale el cursor (una conexión
con RLS activo, ver db.conexion_usuario) y el join de variantes, que ahora
apunta a productos_padre.id (la clave propia) en vez de id_meli. La «curva de
talles» (M/L/XL fijos, solo para ropa) se reemplazó por la cobertura de
variantes clave, que sirve para cualquier rubro (pivot multi-rubro).

Los "..._y_alertar" del original (que mandaban el aviso por WhatsApp)
todavía no se portaron — CoreLux no tiene el puente de WhatsApp
conectado por ahora. Lo que sí está acá es la detección pura, que es lo
que consumen las páginas y APIs del dashboard.
"""
from datetime import timedelta
from utils import hoy_argentina, limpiar_titulo_modelo

VENTANA_DIAS = 14
UMBRAL_DIAS_RESTANTES = 5


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


def dias_de_stock(stock_total, unidades_vendidas, ventana_dias=VENTANA_DIAS):
    """Cuántos días alcanza el stock al ritmo de venta de la ventana. None si no hubo ventas: sin ritmo no hay nada que estimar (y un 0 diría "se agota hoy")."""
    if not unidades_vendidas or unidades_vendidas <= 0:
        return None
    return round(stock_total / (unidades_vendidas / ventana_dias), 1)


def presentar_dias_de_stock(dias, stock_total):
    """(texto, tono) para la columna "Alcanza para" de Stock. Rojo si queda menos que el umbral de reposición, naranja hasta dos semanas, neutro el resto."""
    if stock_total <= 0:
        return "Agotado", "danger"
    if dias is None:
        return "—", "neutral"          # sin ventas no hay ritmo: un guion (la columna de al lado ya dice "Sin ventas")
    if dias >= 365:
        return "+1 año", "neutral"
    if dias >= 90:
        return "+90 días", "neutral"
    if dias < 1:
        return "menos de 1 día", "danger"
    redondeado = round(dias)       # el color sigue al número que se ve: «~5 días» no puede estar en naranja si 5 es el límite del rojo
    return f"~{redondeado} {'día' if redondeado == 1 else 'días'}", "danger" if redondeado <= UMBRAL_DIAS_RESTANTES else ("warn" if redondeado <= VENTANA_DIAS else "neutral")


UMBRAL_VARIANTE_CLAVE = 0.30        # una variante es «clave» si aporta más del 30 % de las ventas de su modelo
MIN_UNIDADES_MODELO = 5             # con menos ventas que esto en la ventana, el reparto entre variantes no dice nada
VENTANA_COBERTURA_DIAS = 30


def variantes_clave_agotadas(filas, umbral=UMBRAL_VARIANTE_CLAVE, minimo_unidades=MIN_UNIDADES_MODELO):
    """
    Las variantes sin stock que son clave de su modelo. `filas` son dicts con: modelo (la familia de Mercado Libre; sin familia, la publicación), id_variante, id_meli, titulo, talle, etiqueta,
    stock (propio + FULL) y unidades (vendidas en la ventana). Una variante es CLAVE si aporta más de `umbral` de las unidades del modelo; si además se quedó sin stock, avisa. Sirve para un
    buzo talle M, un disco de 1 TB o un celular de 128 GB: no hay talles fijos. Un modelo con UNA sola variante no cuenta (eso es un producto agotado, que ya avisa «Se agota pronto»),
    ni uno con menos de `minimo_unidades` vendidas en la ventana. Devuelve las más vendidas primero.
    """
    por_modelo = {}
    for f in filas:
        por_modelo.setdefault(f["modelo"], []).append(f)
    avisos = []
    for variantes in por_modelo.values():
        total = sum(v["unidades"] for v in variantes)
        if len(variantes) < 2 or total < minimo_unidades:
            continue
        for v in variantes:
            aporte = v["unidades"] / total
            if aporte > umbral and v["stock"] <= 0:
                avisos.append({
                    "modelo": limpiar_titulo_modelo(v["titulo"], v["talle"]) or v["titulo"], "id_referencia": v["id_meli"], "id_variante": v["id_variante"],
                    "variante": v["etiqueta"] or v["talle"] or "Única", "aporta_pct": round(aporte * 100), "unidades": v["unidades"],
                })
    avisos.sort(key=lambda a: -a["unidades"])
    return avisos


def evaluar_cobertura_variantes(cursor):
    """
    «Cobertura de variantes clave» (reemplaza a la curva de talles M/L/XL, que solo existía para ropa): avisa cuando se queda sin stock la variante que aporta más del 30 % de las ventas
    de su modelo en los últimos 30 días. El modelo es la familia de Mercado Libre (`family_id`; sin familia, la publicación con sus variaciones) y la variante, cada publicación o variación
    con su propio stock. Se cuentan las activas y las pausadas (Mercado Libre pausa sola una publicación que llega a cero).
    """
    hasta = hoy_argentina()
    cursor.execute("""
        SELECT COALESCE(p.family_id, p.id_meli), v.id_variante, p.id_meli, p.titulo, v.talle, v.etiqueta,
               COALESCE(v.stock_propio, 0) + COALESCE(v.stock_full, 0), COALESCE(s.unidades, 0)
        FROM productos_variantes v
        JOIN productos_padre p ON p.id = v.id_padre
        LEFT JOIN (SELECT id_variante, SUM(cantidad) AS unidades FROM ventas WHERE fecha_venta BETWEEN %s AND %s AND origen = 'meli' GROUP BY id_variante) s ON s.id_variante = v.id_variante
        WHERE p.estado IN ('active', 'paused')
    """, (hasta - timedelta(days=VENTANA_COBERTURA_DIAS), hasta))
    filas = [dict(zip(("modelo", "id_variante", "id_meli", "titulo", "talle", "etiqueta", "stock", "unidades"), f)) for f in cursor.fetchall()]
    return variantes_clave_agotadas(filas)

"""Comparador Logística Propia vs. FULL — portado de Santi Mens."""
import db
import facturacion
from utils import formatear_moneda


def calcular_comparacion(usuario_id, cuenta_id, access_token, fecha_desde, fecha_hasta):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT v.id_meli, v.cantidad, v.precio_venta, v.cargo_venta, v.costo_envio,
                   COALESCE(p.tipo_logistica, 'desconocido'), COALESCE(p.precio_costo, 0)
            FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.fecha_venta BETWEEN %s AND %s
        """, (fecha_desde, fecha_hasta))
        filas = cursor.fetchall()

    # 3 canales, no 2: "self_service" es Flex (el vendedor entrega, MeLi
    # solo intermedia el envío) — antes caía adentro de "propia" junto
    # con drop_off/cross_docking (envío clásico por correo), mezclando
    # dos operativas bien distintas en un solo número.
    grupos = {
        "full": {"nombre": "FULL", "unidades": 0, "facturado": 0.0, "comision": 0.0, "envio": 0.0, "costo_fab": 0.0},
        "flex": {"nombre": "Flex", "unidades": 0, "facturado": 0.0, "comision": 0.0, "envio": 0.0, "costo_fab": 0.0},
        "propia": {"nombre": "Envíos clásicos", "unidades": 0, "facturado": 0.0, "comision": 0.0, "envio": 0.0, "costo_fab": 0.0},
    }

    for id_meli, cantidad, precio_venta, cargo_venta, costo_envio, tipo_logistica, precio_costo in filas:
        if tipo_logistica == "fulfillment":
            clave = "full"
        elif tipo_logistica == "self_service":
            clave = "flex"
        else:
            clave = "propia"
        grupo = grupos[clave]
        grupo["unidades"] += cantidad
        grupo["facturado"] += float(precio_venta) * cantidad
        grupo["comision"] += float(cargo_venta or 0)
        grupo["envio"] += float(costo_envio or 0)
        grupo["costo_fab"] += float(precio_costo or 0) * cantidad

    costo_almacenamiento_full = None
    cantidad_cargos_almacenamiento = 0
    try:
        if access_token:
            period_key = fecha_hasta[:7] + "-01"
            costo_almacenamiento_full, cantidad_cargos_almacenamiento = facturacion.obtener_costo_almacenamiento_full(access_token, cuenta_id, period_key)
    except Exception as e:
        print(f"[Comparador Logística] ⚠️ No se pudo traer el costo de almacenamiento: {e}")

    resultado = []
    for clave, grupo in grupos.items():
        almacenamiento_grupo = costo_almacenamiento_full if (clave == "full" and costo_almacenamiento_full) else 0.0
        ganancia_neta = grupo["facturado"] - grupo["comision"] - grupo["envio"] - grupo["costo_fab"] - almacenamiento_grupo
        margen_pct = round((ganancia_neta / grupo["facturado"]) * 100, 1) if grupo["facturado"] > 0 else 0.0
        ganancia_por_unidad = round(ganancia_neta / grupo["unidades"], 2) if grupo["unidades"] > 0 else 0.0
        resultado.append({
            "nombre": grupo["nombre"], "unidades": grupo["unidades"],
            "facturado_formateado": formatear_moneda(grupo["facturado"]),
            "comision_formateada": formatear_moneda(grupo["comision"]),
            "envio_formateado": formatear_moneda(grupo["envio"]),
            "costo_fab_formateado": formatear_moneda(grupo["costo_fab"]),
            "almacenamiento_formateado": formatear_moneda(almacenamiento_grupo) if almacenamiento_grupo else None,
            "ganancia_neta_formateada": formatear_moneda(ganancia_neta),
            "ganancia_por_unidad_formateada": formatear_moneda(ganancia_por_unidad),
            "margen_pct": margen_pct, "sin_datos": grupo["unidades"] == 0
        })

    return resultado, cantidad_cargos_almacenamiento

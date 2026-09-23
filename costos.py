"""Costos — portado de Santi Mens. Lógica de negocio idéntica; cambia
el origen del cursor (RLS) y los placeholders (%s en vez de ?).

Los gastos RECURRENTES (alquiler, sueldos, abonos) se prorratean por
día dentro del período que se esté mirando — si elegís 14 días, un
gasto recurrente de $150.000/mes cuenta como $150.000 * 14/30, no el
mes entero ni $0. Esto se decidió así a propósito en vez de contar el
mes completo siempre, para que el número tenga sentido en períodos
cortos como "últimos 7 días"."""
from datetime import datetime, timedelta
from psycopg.rows import dict_row
import db
from utils import formatear_moneda

DIAS_MES_REFERENCIA = 30  # para prorratear "monto mensual" a días


def _dias_de_solapamiento(fecha_inicio_gasto, fecha_fin_gasto, fecha_desde_periodo, fecha_hasta_periodo):
    inicio = max(fecha_inicio_gasto, fecha_desde_periodo)
    fin = min(fecha_fin_gasto or fecha_hasta_periodo, fecha_hasta_periodo)
    return max((fin - inicio).days + 1, 0)


def obtener_datos_costos(usuario_id, fecha_desde, fecha_hasta):
    fecha_desde_dt = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
    fecha_hasta_dt = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT id, concepto, categoria, monto, fecha, recurrente, fecha_fin FROM gastos_operativos
            WHERE (recurrente = false AND fecha BETWEEN %s AND %s)
               OR (recurrente = true AND fecha <= %s AND (fecha_fin IS NULL OR fecha_fin >= %s))
            ORDER BY fecha DESC, id DESC
        """, (fecha_desde, fecha_hasta, fecha_hasta, fecha_desde))
        gastos_db = cursor.fetchall()

        gastos = []
        total_fijos = 0.0
        total_variables = 0.0
        for fila in gastos_db:
            monto_base = float(fila["monto"])
            if fila["recurrente"]:
                dias = _dias_de_solapamiento(fila["fecha"], fila["fecha_fin"], fecha_desde_dt, fecha_hasta_dt)
                monto = round(monto_base * (dias / DIAS_MES_REFERENCIA), 2)
            else:
                monto = monto_base

            if fila["categoria"] == "fijo": total_fijos += monto
            else: total_variables += monto

            fecha_fmt = fila["fecha"].strftime("%Y-%m-%d") if hasattr(fila["fecha"], "strftime") else fila["fecha"]
            gastos.append({
                "id": fila["id"], "concepto": fila["concepto"], "categoria": fila["categoria"],
                "monto_formateado": formatear_moneda(monto), "fecha": fecha_fmt,
                "recurrente": fila["recurrente"],
                "monto_mensual_formateado": formatear_moneda(monto_base) if fila["recurrente"] else None,
            })

        cursor.execute("""
            SELECT p.id_meli, p.titulo, p.precio_costo, p.estado, p.thumbnail, p.proveedor_id, p.precio, p.recibis_estimado
            FROM productos_padre p
            ORDER BY CASE WHEN p.estado = 'active' THEN 0 ELSE 1 END, p.titulo
        """)
        filas_costo = cursor.fetchall()

        # Estas dos consultas antes leían por posición (r[0], r[1]...) —
        # con dict_row el resultado es un diccionario, así que hace falta
        # el nombre real de columna. Le puse alias explícito a AVG() para
        # no depender del nombre que Postgres le pone por default a una
        # columna calculada sin alias.
        cursor.execute("SELECT id_meli, AVG(costo_envio) AS envio_promedio FROM ventas WHERE costo_envio > 0 GROUP BY id_meli")
        envio_promedio_por_item = {r["id_meli"]: float(r["envio_promedio"]) for r in cursor.fetchall()}

        cursor.execute("SELECT id, nombre, tiempo_entrega_dias FROM proveedores ORDER BY nombre")
        proveedores = [{"id": pr["id"], "nombre": pr["nombre"], "tiempo_entrega_dias": pr["tiempo_entrega_dias"]} for pr in cursor.fetchall()]

    productos_costo = []
    for fila in filas_costo:
        precio_costo_p = float(fila["precio_costo"] or 0.0)
        precio_p = float(fila["precio"] or 0.0)
        recibis_p = float(fila["recibis_estimado"]) if fila["recibis_estimado"] is not None else None
        comision_est = round(precio_p - recibis_p, 2) if recibis_p else None
        envio_prom = round(envio_promedio_por_item.get(fila["id_meli"], 0.0), 2)
        ganancia_neta = None
        segmentos_pct = None
        if comision_est is not None and precio_p > 0:
            ganancia_neta = round(precio_p - comision_est - envio_prom - precio_costo_p, 2)
            segmentos_pct = {
                "costo": round((precio_costo_p / precio_p) * 100, 1),
                "envio": round((envio_prom / precio_p) * 100, 1),
                "comision": round((comision_est / precio_p) * 100, 1),
                "ganancia": round(max(ganancia_neta, 0) / precio_p * 100, 1),
            }
        productos_costo.append({
            "id": fila["id_meli"], "titulo": fila["titulo"], "precio_costo": precio_costo_p,
            "precio_costo_formateado": formatear_moneda(precio_costo_p), "estado": fila["estado"],
            "thumbnail": fila["thumbnail"], "proveedor_id": fila["proveedor_id"],
            "precio_formateado": formatear_moneda(precio_p) if precio_p else None,
            "comision_formateada": formatear_moneda(comision_est) if comision_est is not None else None,
            "envio_formateado": formatear_moneda(envio_prom) if envio_prom else None,
            "ganancia_neta_formateada": formatear_moneda(ganancia_neta) if ganancia_neta is not None else None,
            "ganancia_negativa": ganancia_neta is not None and ganancia_neta < 0,
            "segmentos_pct": segmentos_pct,
        })

    stats_gastos = {"fijos": formatear_moneda(total_fijos), "variables": formatear_moneda(total_variables), "total": formatear_moneda(total_fijos + total_variables)}
    return gastos, stats_gastos, productos_costo, proveedores

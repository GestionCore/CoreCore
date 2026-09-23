"""Flujo de Caja — proyección de liberaciones a 14 días. Portado de Santi Mens."""
from datetime import datetime, timedelta
import db


def obtener_proyeccion_14_dias(usuario_id):
    hoy = datetime.now().date()
    fecha_desde = hoy.strftime("%Y-%m-%d")
    fecha_hasta = (hoy + timedelta(days=14)).strftime("%Y-%m-%d")

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT fecha_liberacion, COALESCE(SUM(monto_liberacion), 0), COUNT(*)
            FROM ventas
            WHERE fecha_liberacion BETWEEN %s AND %s
            GROUP BY fecha_liberacion
        """, (fecha_desde, fecha_hasta))
        filas_db = {}
        for fecha, monto, cantidad in cursor.fetchall():
            fecha_str = fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else fecha
            filas_db[fecha_str] = {"monto": float(monto), "cantidad": cantidad}

    dias = []
    for i in range(15):
        fecha = (hoy + timedelta(days=i)).strftime("%Y-%m-%d")
        info = filas_db.get(fecha, {"monto": 0.0, "cantidad": 0})
        dias.append({"fecha": fecha, "monto": round(info["monto"], 2), "cantidad": info["cantidad"], "es_hoy": i == 0})

    return dias

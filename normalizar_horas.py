"""
Corrige la hora de las ventas viejas: Mercado Libre informa las órdenes con offset -04:00 y hasta ahora se guardaba esa hora tal cual, una hora
atrasada respecto de la hora argentina (UTC-3). Una venta de 00:30 quedaba en el día anterior y el mapa de "cuándo te compran" salía corrido.

  python normalizar_horas.py            vista previa: cuántas ventas se desplazan y cuántas cambian de día (no modifica nada)
  python normalizar_horas.py --aplicar  desplaza una hora las ventas de Mercado Libre que todavía no están normalizadas y las marca

Es seguro repetirlo: solo toca filas con hora_normalizada = false y las marca al terminar, así que una fila nunca se desplaza dos veces. Las ventas que
escribe el sync nuevo ya entran normalizadas. Usa conexion_admin porque recorre todas las cuentas (excepción documentada, como rotar_clave.py).
"""
import sys

import db

CONDICION = "origen = 'meli' AND NOT hora_normalizada AND fecha_venta IS NOT NULL AND hora_venta IS NOT NULL"


def main(aplicar=False):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(f"""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE hora_venta >= TIME '23:00'),
                   COUNT(DISTINCT cuenta_id)
            FROM ventas WHERE {CONDICION}
        """)
        total, cambian_de_dia, cuentas = cursor.fetchone()
        print(f"Ventas de Mercado Libre sin normalizar: {total} en {cuentas} cuenta(s) · {cambian_de_dia} cambiarían de día (las de 23:00 a 23:59).")
        if not total:
            return
        if not aplicar:
            print("Vista previa: no se modificó nada. Para corregirlas, correr con --aplicar.")
            return
        cursor.execute(f"""
            UPDATE ventas SET
                fecha_venta = (fecha_venta + hora_venta + INTERVAL '1 hour')::date,
                hora_venta = (fecha_venta + hora_venta + INTERVAL '1 hour')::time,
                hora_normalizada = true
            WHERE {CONDICION}
        """)
        print(f"✅ {cursor.rowcount} ventas corregidas a hora argentina.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(aplicar="--aplicar" in sys.argv)

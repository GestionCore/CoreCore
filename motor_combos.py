"""
Combos sugeridos — portado de Santi Mens. Dos ajustes reales:
1. `date('now', '-90 days')` es sintaxis de SQLite — se resuelve la
   fecha límite en Python y se pasa ya calculada.
2. El esquema de Postgres nombra la columna de conteo `veces_juntos`
   (no `veces_comprados_juntos` como en el original) y no tiene columna
   de última detección — se ajustó el módulo a lo que ya quedó definido
   en 01_schema_multitenant.sql en vez de agregar una migración para
   esto todavía.
"""
from datetime import timedelta
from itertools import combinations
from utils import hoy_argentina

UMBRAL_MINIMO_VECES = 3


def analizar_combos(cursor, cuenta_id):
    fecha_desde = (hoy_argentina() - timedelta(days=90)).strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id_orden, id_meli FROM ventas
        WHERE fecha_venta >= %s
        GROUP BY id_orden, id_meli
    """, (fecha_desde,))
    filas = cursor.fetchall()

    ordenes = {}
    for id_orden, id_meli in filas:
        ordenes.setdefault(id_orden, set()).add(id_meli)

    conteo_pares = {}
    for items in ordenes.values():
        if len(items) < 2:
            continue
        for a, b in combinations(sorted(items), 2):
            conteo_pares[(a, b)] = conteo_pares.get((a, b), 0) + 1

    validos = 0
    for (a, b), veces in conteo_pares.items():
        if veces >= UMBRAL_MINIMO_VECES:
            cursor.execute("""
                INSERT INTO combos_sugeridos (cuenta_id, id_meli_a, id_meli_b, veces_juntos)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (cuenta_id, id_meli_a, id_meli_b) DO UPDATE SET veces_juntos = excluded.veces_juntos
            """, (cuenta_id, a, b, veces))
            validos += 1

    cursor.execute("SELECT id_meli_a, id_meli_b FROM combos_sugeridos")
    for a, b in cursor.fetchall():
        if conteo_pares.get((a, b), 0) < UMBRAL_MINIMO_VECES:
            cursor.execute("DELETE FROM combos_sugeridos WHERE id_meli_a = %s AND id_meli_b = %s", (a, b))

    return validos


def obtener_combos_sugeridos(cursor):
    cursor.execute("""
        SELECT c.id_meli_a, c.id_meli_b, c.veces_juntos, pa.titulo, pb.titulo
        FROM combos_sugeridos c
        LEFT JOIN productos_padre pa ON pa.id_meli = c.id_meli_a
        LEFT JOIN productos_padre pb ON pb.id_meli = c.id_meli_b
        ORDER BY c.veces_juntos DESC
        LIMIT 12
    """)
    return [
        {"id_meli_a": a, "id_meli_b": b, "titulo_a": ta or a, "titulo_b": tb or b, "veces": veces}
        for a, b, veces, ta, tb in cursor.fetchall()
    ]

"""
Unidades que están en las bodegas de FULL pero no se pueden vender (dañadas, perdidas, en traslado...). El dato lo completa
enriquecimiento.refrescar_full desde GET /inventories/{inventory_id}/stock/fulfillment; acá solo se lee y se ordena para mostrarlo.

Varias publicaciones pueden compartir el mismo inventario: las unidades se cuentan UNA vez por inventory_id.
"""

MOTIVOS = {
    "lost": "perdidas", "damage": "dañadas", "damaged": "dañadas", "noFiscalCoverage": "sin cobertura fiscal",
    "withdrawal": "en retiro", "internalProcess": "en proceso interno de Mercado Libre", "internal_process": "en proceso interno de Mercado Libre",
    "transfer": "en traslado entre bodegas",
}


def unidades_no_disponibles(cursor, cuenta_id):
    """{"total": n, "items": [{titulo, thumbnail, permalink, estado, cantidad, motivos: [{texto, cantidad}]}]} — vacío si no hay nada."""
    cursor.execute("""
        SELECT DISTINCT ON (inventory_id) inventory_id, titulo, thumbnail, permalink, estado, full_no_disponible, full_detalle
        FROM productos_padre
        WHERE cuenta_id = %s AND inventory_id IS NOT NULL AND full_no_disponible > 0
        ORDER BY inventory_id, (estado = 'active') DESC
    """, (cuenta_id,))
    items = []
    for _inv, titulo, thumbnail, permalink, estado, cantidad, detalle in cursor.fetchall():
        motivos = [{"texto": MOTIVOS.get(d.get("status"), str(d.get("status") or "otro motivo")), "cantidad": int(d.get("quantity") or 0)}
                   for d in (detalle if isinstance(detalle, list) else []) if int(d.get("quantity") or 0) > 0]
        items.append({"titulo": titulo, "thumbnail": thumbnail, "permalink": permalink, "estado": estado, "cantidad": int(cantidad), "motivos": motivos})
    items.sort(key=lambda i: -i["cantidad"])
    return {"total": sum(i["cantidad"] for i in items), "items": items}

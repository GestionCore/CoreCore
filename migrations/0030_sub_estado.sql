-- Motivo de la pausa de una publicación (sub_status de Mercado Libre, varios separados por coma): "out_of_stock" cuando se pausó sola por
-- quedarse sin stock, vacío si la pausó el vendedor, y los de moderación o bloqueo ("suspended", "under_review"…) que no se pueden
-- reactivar desde acá. NULL = todavía no se sincronizó después de esta migración.
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS sub_estado TEXT;

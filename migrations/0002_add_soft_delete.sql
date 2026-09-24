-- Migración 0002: soft delete en gastos_operativos y ventas (origen manual)
--
-- Fase 4 (UX de datos) necesita poder "deshacer" una eliminación durante
-- los 6 segundos del toast. El patrón: columna eliminado_en TIMESTAMPTZ;
-- el registro se oculta de las queries normales (WHERE eliminado_en IS NULL),
-- y solo se borra definitivamente si el usuario no hace clic en "Deshacer"
-- dentro del plazo.
--
-- Por ahora solo se aplica a las tablas donde los errores de borrado son
-- más costosos: gastos operativos (afectan Ganancia Neta Real) y ventas
-- manuales (las únicas ventas que el usuario puede borrar — las de MeLi
-- vuelven solas en el próximo sync).
--
-- Las ventas de MeLi (origen='meli') NO se borran nunca desde la UI;
-- el soft delete en 'ventas' aplica solo a origen='manual'.

ALTER TABLE gastos_operativos
    ADD COLUMN IF NOT EXISTS eliminado_en TIMESTAMPTZ;

-- Índice parcial para la query más común (solo los no eliminados)
CREATE INDEX IF NOT EXISTS idx_gastos_activos
    ON gastos_operativos (cuenta_id, fecha)
    WHERE eliminado_en IS NULL;

ALTER TABLE ventas
    ADD COLUMN IF NOT EXISTS eliminado_en TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ventas_manuales_activas
    ON ventas (cuenta_id, fecha_venta)
    WHERE eliminado_en IS NULL AND origen = 'manual';

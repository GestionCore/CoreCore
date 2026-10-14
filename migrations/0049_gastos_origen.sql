-- Gastos operativos que CoreLux registra solo (con su origen y la orden a la que pertenecen).
--
-- Caso de hoy: una orden Flex que ya se entregó con tu propia logística y después se cancela o se devuelve. El envío de ida igual se pagó y no se recupera,
-- pero al cancelarse la orden sale de `ventas` y ese costo desaparecía de todos los números. Ahora queda como un gasto operativo (origen 'flex_ida'), y el
-- costo del envío de vuelta que cargue la persona como otro (origen 'flex_vuelta'); `referencia` es el id de la orden de Mercado Libre.
--
-- La clave única (cuenta, origen, referencia) hace que registrar lo mismo dos veces no duplique nada. Los gastos que carga la persona a mano tienen
-- origen NULL y quedan fuera de la clave (puede haber tantos como quiera).

ALTER TABLE gastos_operativos ADD COLUMN IF NOT EXISTS origen TEXT;
ALTER TABLE gastos_operativos ADD COLUMN IF NOT EXISTS referencia TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_gastos_origen_referencia ON gastos_operativos (cuenta_id, origen, referencia) WHERE origen IS NOT NULL;

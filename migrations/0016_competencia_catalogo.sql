-- Espía de Competencia: Mercado Libre dejó de exponer por API el precio, el
-- stock y las ventas de publicaciones de otros vendedores (GET /items/{id}
-- ajeno devuelve 403), así que la sección pasa a seguir PRODUCTOS DE CATÁLOGO:
-- cada día se guarda cuántas ofertas y vendedores hay, y cómo se distribuye el
-- precio entre ellas. `precio` sigue siendo el precio más bajo ofrecido.
-- Las columnas viejas (stock_disponible, sold_quantity, foto_principal_id)
-- quedan sin uso — no se borran para no perder historial de ninguna cuenta.

ALTER TABLE competidores_historial ADD COLUMN IF NOT EXISTS ofertas INTEGER;
ALTER TABLE competidores_historial ADD COLUMN IF NOT EXISTS vendedores INTEGER;
ALTER TABLE competidores_historial ADD COLUMN IF NOT EXISTS precio_mediano NUMERIC(12,2);
ALTER TABLE competidores_historial ADD COLUMN IF NOT EXISTS precio_max NUMERIC(12,2);
ALTER TABLE competidores_historial ADD COLUMN IF NOT EXISTS pct_full NUMERIC(5,1);

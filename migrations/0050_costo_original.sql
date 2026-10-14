-- Costo de fabricación en la moneda en que la persona lo cargó (pesos o dólares).
--
-- `precio_costo` SIGUE siendo el costo en PESOS que leen las pantallas y la Ganancia Real: no se toca ninguna de esas consultas. Ahora, además:
--   costo_original = lo que la persona escribió (en pesos o en dólares),
--   moneda_costo   = 'ARS' o 'USD' (la columna ya existe desde la migración 0046).
-- Cuando la moneda es USD, precio_costo = costo_original × la cotización activa de la cuenta (el dólar MEP automático o su dólar manual), y se vuelve a calcular cada vez
-- que esa cotización cambia (costos_moneda.recalcular_cuenta): así la Ganancia Real siempre usa el costo de reposición de hoy.
-- Lo cargado hasta hoy está en pesos: costo_original = precio_costo, moneda 'ARS'.

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS costo_original NUMERIC(14,2);
ALTER TABLE productos_variantes ADD COLUMN IF NOT EXISTS costo_original NUMERIC(14,2);

UPDATE productos_padre SET costo_original = precio_costo WHERE costo_original IS NULL AND precio_costo IS NOT NULL;
UPDATE productos_variantes SET costo_original = precio_costo WHERE costo_original IS NULL AND precio_costo IS NOT NULL;

ALTER TABLE productos_padre DROP CONSTRAINT IF EXISTS productos_padre_costo_original_valido;
ALTER TABLE productos_padre ADD CONSTRAINT productos_padre_costo_original_valido CHECK (costo_original IS NULL OR costo_original >= 0);
ALTER TABLE productos_variantes DROP CONSTRAINT IF EXISTS productos_variantes_costo_original_valido;
ALTER TABLE productos_variantes ADD CONSTRAINT productos_variantes_costo_original_valido CHECK (costo_original IS NULL OR costo_original >= 0);

-- Un costo en dólares sin su valor en dólares no se puede volver a convertir: no se permite
ALTER TABLE productos_padre DROP CONSTRAINT IF EXISTS productos_padre_usd_con_original;
ALTER TABLE productos_padre ADD CONSTRAINT productos_padre_usd_con_original CHECK (moneda_costo IS DISTINCT FROM 'USD' OR costo_original IS NOT NULL);
ALTER TABLE productos_variantes DROP CONSTRAINT IF EXISTS productos_variantes_usd_con_original;
ALTER TABLE productos_variantes ADD CONSTRAINT productos_variantes_usd_con_original CHECK (moneda_costo IS DISTINCT FROM 'USD' OR costo_original IS NOT NULL);

-- Flex: elegir la zona de cada envío a mano no escala (una cuenta puede tener
-- 100+ envíos Flex por mes). Se guarda la localidad y el código postal de cada
-- envío, y la zona que el usuario elige para una localidad (o un código postal
-- puntual, que tiene prioridad) queda recordada en cuentas_meli.flex_zonas_memoria
-- para aplicarse sola a los envíos nuevos.
--
-- flex_zonas_memoria: {"loc:buenos aires|lanus": 2, "cp:1405": 1}

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS codigo_postal TEXT;
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS localidad TEXT;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_zonas_memoria JSONB NOT NULL DEFAULT '{}'::jsonb;

-- flex_zona = 0 significa "sin costo de entrega" (por ejemplo, entrega el propio vendedor): la orden queda resuelta
-- en vez de figurar como pendiente, y la memoria de zonas no se la vuelve a pisar.
ALTER TABLE ventas DROP CONSTRAINT IF EXISTS ventas_flex_zona_check;
ALTER TABLE ventas ADD CONSTRAINT ventas_flex_zona_check CHECK (flex_zona BETWEEN 0 AND 3);

-- Costo de entrega de Flex. En Flex el vendedor entrega con su propia logística
-- (moto, cadete, flete) y esa logística le cobra según la distancia desde el
-- domicilio de entrega, dividida en 3 zonas con precio distinto. Mercado Libre
-- no conoce ese costo (las ventas Flex vienen con costo_envio = 0), así que lo
-- carga el usuario: 3 precios por cuenta y la zona de cada venta.
--
-- ventas.costo_envio pasa a ser "envío total que te cuesta": lo que informa MeLi
-- + ventas.costo_flex. Así Ganancia Real, Dashboard, Facturación y el reporte
-- fiscal lo incluyen sin tocar cada cálculo (todos ya suman costo_envio).
-- ventas_sync respeta costo_flex al reprocesar una orden.

ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_tarifa_zona1 NUMERIC(12,2);
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_tarifa_zona2 NUMERIC(12,2);
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_tarifa_zona3 NUMERIC(12,2);

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS flex_zona SMALLINT CHECK (flex_zona BETWEEN 1 AND 3);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS costo_flex NUMERIC(12,2) NOT NULL DEFAULT 0;

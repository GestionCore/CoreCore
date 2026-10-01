-- Flex: las logísticas cobran por distancia desde el domicilio de salida, en 3 zonas. MeLi trae las coordenadas exactas
-- del destino de cada envío; con el código postal de salida del vendedor (que MeLi resuelve a coordenadas) y hasta
-- cuántos km llega cada zona, la zona se calcula sola. Es opcional: sin estos datos la zona se elige a mano (0018/0019).
--
-- Zona 1 = hasta flex_km_zona1 km · Zona 2 = hasta flex_km_zona2 km · Zona 3 = más lejos.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS destino_lat NUMERIC(9,6);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS destino_lon NUMERIC(9,6);

ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_origen_cp TEXT;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_origen_lat NUMERIC(9,6);
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_origen_lon NUMERIC(9,6);
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_km_zona1 NUMERIC(6,1);
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_km_zona2 NUMERIC(6,1);

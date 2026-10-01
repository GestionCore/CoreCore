-- Flex v2: las zonas las define Mercado Libre, no el usuario. MeLi publica las zonas de cobertura del servicio Flex de
-- cada vendedor (GET /flex/sites/{site}/users/{user}/services/{service}/configurations/coverage/zones/v1) y trae el
-- domicilio de salida en la suscripción. El usuario solo carga lo que le cobra su logística: "umbrales" con un precio y
-- las zonas que cubre; las zonas que no mueve a ningún umbral caen en el umbral "resto".
--
-- Reemplaza el modelo de 0018-0020 (3 zonas fijas, memoria por localidad, regla de distancia por km), que pedía datos
-- que el usuario no tiene y nunca llegó a producción: las columnas se verificaron vacías antes de borrarlas.
--
-- cuentas_meli.flex_umbrales: [{"id": 1, "nombre": null, "precio": 8690, "zonas": [], "resto": true}, ...]
-- cuentas_meli.flex_info:     {"service_id": 5010032, "origen": {...}, "zonas": [{"id": "Quilmes", "nombre": "Quilmes"}], "sincronizado_en": "..."}
-- ventas.flex_zona:           id del umbral aplicado (1..99); 0 = sin costo (entrega el propio vendedor); NULL = pendiente
-- ventas.flex_zona_meli:      zona de MeLi en la que se ubicó el envío; '*manual' si el usuario eligió el umbral a mano

ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_umbrales JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS flex_info JSONB;
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS flex_zona_meli TEXT;

ALTER TABLE ventas DROP CONSTRAINT IF EXISTS ventas_flex_zona_check;
ALTER TABLE ventas ADD CONSTRAINT ventas_flex_zona_check CHECK (flex_zona BETWEEN 0 AND 99);

ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_tarifa_zona1;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_tarifa_zona2;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_tarifa_zona3;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_zonas_memoria;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_origen_cp;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_origen_lat;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_origen_lon;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_km_zona1;
ALTER TABLE cuentas_meli DROP COLUMN IF EXISTS flex_km_zona2;

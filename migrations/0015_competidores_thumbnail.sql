-- Espía de Competencia ya traía la foto principal del rival en cada
-- relevo (se usaba solo el ID de la foto, para detectar si cambió) pero
-- nunca guardaba la URL en sí — la pantalla mostraba cada rival como
-- puro texto, sin imagen, a diferencia del resto del catálogo propio.

ALTER TABLE competidores_seguimiento ADD COLUMN IF NOT EXISTS thumbnail TEXT;

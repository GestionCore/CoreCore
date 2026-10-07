-- Cuándo se hizo cada pregunta (la hora que informa Mercado Libre, no la de nuestro sync) y hasta cuándo conviene responderla.
-- OJO: la respuesta real de GET /questions/search NO trae ningún campo de plazo (solo `date_created`); `hora_limite_respuesta` es un objetivo interno de CoreLux
-- (fecha_pregunta + preguntas_sla.SLA_MINUTOS), no una fecha que Mercado Libre informe.
-- Sin relleno de filas viejas a propósito: las pendientes se completan solas en el próximo sync (cada 4 min o por el webhook de `questions`).
ALTER TABLE preguntas_pendientes ADD COLUMN IF NOT EXISTS fecha_pregunta TIMESTAMPTZ;
ALTER TABLE preguntas_pendientes ADD COLUMN IF NOT EXISTS hora_limite_respuesta TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_preguntas_pendientes_limite ON preguntas_pendientes (cuenta_id, hora_limite_respuesta) WHERE estado = 'pendiente';

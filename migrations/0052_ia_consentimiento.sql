-- Consentimiento para usar las funciones con IA (2026-10-22, N26 del plan de la beta).
--
-- El asistente, las sugerencias de respuesta, la optimización de títulos, el coach de Logros y la carga de gastos por chat mandan texto a un proveedor externo de
-- inteligencia artificial. Mercado Libre pide que eso no se haga con datos de la cuenta sin que la persona lo sepa y lo acepte, así que cada persona lo elige
-- (al empezar y, cuando quiera, en Mi cuenta). NULL = no aceptó (las funciones con IA no se ofrecen); con fecha = aceptó ese día.
--
-- Aditiva e idempotente. Quienes ya usan CoreLux quedan sin aceptar hasta que lo activen ellos.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ia_consentimiento_en TIMESTAMPTZ;

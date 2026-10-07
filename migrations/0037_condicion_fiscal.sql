-- Condición fiscal de cada cuenta de Mercado Libre. NULL = no la sabemos: la app nunca la supone (no todos los vendedores son monotributistas: hay responsables
-- inscriptos y quien todavía no está inscripto). Se guarda por cuenta porque cada cuenta de MeLi puede tener su propio CUIT. Valores:
--   monotributo · responsable_inscripto · sin_inscripcion
-- `condicion_fiscal_origen` dice de dónde salió ("declarada" por la persona; más adelante podría ser "arca" si se consulta el padrón).
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS condicion_fiscal TEXT;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS condicion_fiscal_origen TEXT;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS condicion_fiscal_en TIMESTAMPTZ;
ALTER TABLE cuentas_meli DROP CONSTRAINT IF EXISTS cuentas_meli_condicion_fiscal_valida;
ALTER TABLE cuentas_meli ADD CONSTRAINT cuentas_meli_condicion_fiscal_valida
    CHECK (condicion_fiscal IS NULL OR condicion_fiscal IN ('monotributo', 'responsable_inscripto', 'sin_inscripcion'));

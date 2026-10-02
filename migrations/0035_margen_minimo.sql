-- Margen mínimo aceptable de cada cuenta (en % de lo facturado). Hasta ahora estaba fijo en 15 % en el código: lo que deja menos que eso se marca
-- "al límite" y lo que pierde, en rojo. Cada vendedor tiene su propio piso (quien vende mucho volumen con poco margen no es el mismo que quien vende artesanías).
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS margen_minimo NUMERIC(5,2) NOT NULL DEFAULT 15;
ALTER TABLE cuentas_meli DROP CONSTRAINT IF EXISTS cuentas_meli_margen_minimo_rango;
ALTER TABLE cuentas_meli ADD CONSTRAINT cuentas_meli_margen_minimo_rango CHECK (margen_minimo >= 0 AND margen_minimo <= 60);

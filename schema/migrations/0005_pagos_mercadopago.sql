-- Migración 0005: soporte de pagos por Mercado Pago
-- Correr en Supabase SQL Editor (como postgres).

-- Referencia al ID de suscripción de MP, para consultar estado y cancelar.
ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS mp_suscripcion_id TEXT,
    ADD COLUMN IF NOT EXISTS suscripcion_activada_en TIMESTAMPTZ;

-- Índice para que el webhook pueda buscar por mp_suscripcion_id rápido.
CREATE INDEX IF NOT EXISTS idx_usuarios_mp_suscripcion_id
    ON usuarios (mp_suscripcion_id)
    WHERE mp_suscripcion_id IS NOT NULL;

-- Registrar esta migración
INSERT INTO schema_migrations (version) VALUES ('0005') ON CONFLICT DO NOTHING;

-- Sistema de referidos de CoreLux.
--
-- Agrega un código de referido único a cada usuario y una tabla para
-- registrar quién invitó a quién. Los códigos se generan como los primeros
-- 8 chars del MD5(id || salt) — probabilidad de colisión despreciable para
-- volúmenes normales de usuarios SaaS.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE;

-- Generar códigos para usuarios ya existentes (idempotente por el IF NULL check).
UPDATE usuarios
SET referral_code = UPPER(SUBSTRING(MD5(id::text || 'corelux_ref_v1'), 1, 8))
WHERE referral_code IS NULL;

CREATE TABLE IF NOT EXISTS referrals (
    id              BIGSERIAL PRIMARY KEY,
    referrer_id     BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    referred_id     BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    codigo          TEXT NOT NULL,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    convertido_en   TIMESTAMPTZ,
    UNIQUE (referred_id)
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_codigo ON referrals(codigo);

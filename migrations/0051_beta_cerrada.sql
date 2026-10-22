-- Beta cerrada: entrada con invitación y lista de espera (decisión del dueño, 2026-10-22).
--
-- Quien ya tiene cuenta entra como siempre. Una cuenta NUEVA de Mercado Libre solo se crea si llega con un código de invitación válido; si no tiene, deja su mail
-- en la lista de espera. Las tres tablas son del sistema (no de una cuenta): las lee y escribe solo `beta.py` con la conexión de administración, y las políticas
-- de seguridad por fila quedan sin ninguna política para el rol de la app, así que ninguna pantalla común puede listarlas.
--
-- Todo es aditivo e idempotente.

CREATE TABLE IF NOT EXISTS beta_invitaciones (
    id          BIGSERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,                    -- guardado en mayúsculas, sin espacios (beta.normalizar_codigo)
    nota        TEXT,                                    -- para quién es, solo lo ve el administrador
    usos_max    INTEGER NOT NULL DEFAULT 1 CHECK (usos_max >= 1),
    usos        INTEGER NOT NULL DEFAULT 0 CHECK (usos >= 0),
    activa      BOOLEAN NOT NULL DEFAULT true,
    expira_en   TIMESTAMPTZ,
    creada_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Quién usó cada invitación (una fila por cuenta de CoreLux creada con ella).
CREATE TABLE IF NOT EXISTS beta_canjes (
    id             BIGSERIAL PRIMARY KEY,
    invitacion_id  BIGINT NOT NULL REFERENCES beta_invitaciones(id) ON DELETE CASCADE,
    usuario_id     BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    canjeado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_beta_canjes_invitacion ON beta_canjes (invitacion_id);
CREATE INDEX IF NOT EXISTS idx_beta_canjes_usuario ON beta_canjes (usuario_id);

-- Lista de espera: un mail por fila (sin distinguir mayúsculas), con el rubro que vende para decidir a quién invitar primero.
CREATE TABLE IF NOT EXISTS beta_espera (
    id         BIGSERIAL PRIMARY KEY,
    email      TEXT NOT NULL,
    rubro      TEXT,
    mensaje    TEXT,
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_beta_espera_email ON beta_espera (lower(email));

ALTER TABLE beta_invitaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE beta_canjes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE beta_espera       ENABLE ROW LEVEL SECURITY;

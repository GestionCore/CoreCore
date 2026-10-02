-- Comentarios de los usuarios dentro de la app (ideas, problemas, preguntas), con la pantalla desde la que escribieron y la versión que corría.
-- El usuario puede enviar y leer los suyos; quien administra los lee todos y los marca como atendidos desde /admin/feedback (conexion_admin).

CREATE TABLE IF NOT EXISTS feedback (
    id          BIGSERIAL PRIMARY KEY,
    usuario_id  BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    cuenta_id   BIGINT REFERENCES cuentas_meli(id) ON DELETE SET NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('idea', 'problema', 'pregunta')),
    mensaje     TEXT NOT NULL,
    pantalla    TEXT,
    navegador   TEXT,
    version     TEXT,
    atendido    BOOLEAN NOT NULL DEFAULT false,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_pendientes ON feedback(atendido, creado_en DESC);

ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS feedback_propio ON feedback;
CREATE POLICY feedback_propio ON feedback
    USING (usuario_id = current_setting('app.usuario_actual')::bigint)
    WITH CHECK (usuario_id = current_setting('app.usuario_actual')::bigint);

GRANT SELECT, INSERT ON feedback TO app_backend;
GRANT USAGE, SELECT ON feedback_id_seq TO app_backend;

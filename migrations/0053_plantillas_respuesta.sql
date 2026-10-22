-- Respuestas guardadas para las preguntas de los compradores (2026-10-22, N12 del plan de la beta).
--
-- Responder preguntas es una tarea de todos los días y casi siempre se repite lo mismo («¿tenés stock?», «¿hacen envíos?»). Cada cuenta guarda sus respuestas con un nombre corto
-- y las usa con un clic en cada pregunta; el texto puede llevar {saludo}, {producto} y {precio}, que se completan solos según la pregunta (plantillas_respuesta.py).
--
-- Son de la CUENTA (como todo lo que se carga a mano): una persona con dos cuentas de Mercado Libre tiene las respuestas de cada una por separado.
-- Aditiva e idempotente.

CREATE TABLE IF NOT EXISTS plantillas_respuesta (
    id             BIGSERIAL PRIMARY KEY,
    cuenta_id      BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    titulo         TEXT NOT NULL,
    texto          TEXT NOT NULL,
    usos           INTEGER NOT NULL DEFAULT 0 CHECK (usos >= 0),
    creada_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_plantillas_respuesta_cuenta ON plantillas_respuesta(cuenta_id);

ALTER TABLE plantillas_respuesta ENABLE ROW LEVEL SECURITY;

-- Misma política que `ventas` (migración 0010): cuentas del usuario, y la cuenta activa cuando está seteada.
DROP POLICY IF EXISTS plantillas_respuesta_por_cuenta_propia ON plantillas_respuesta;
CREATE POLICY plantillas_respuesta_por_cuenta_propia ON plantillas_respuesta
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON plantillas_respuesta TO app_backend;
GRANT USAGE, SELECT ON plantillas_respuesta_id_seq TO app_backend;

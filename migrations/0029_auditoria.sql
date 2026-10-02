-- Registro de actividad: quién cambió qué y cuándo (precios y stock masivos, costos, descuentos, edición de publicaciones, respuestas a
-- compradores, cambios de plan, cancelaciones). Sirve para reconstruir "¿quién tocó esto?" cuando una cuenta tiene más de una persona
-- operando o cuando hay que revisar un cambio de plata.
--
-- Es de solo agregar: el rol de la app puede insertar y leer, no modificar ni borrar. Se elimina junto con el usuario (cascada).

CREATE TABLE IF NOT EXISTS auditoria (
    id          BIGSERIAL PRIMARY KEY,
    usuario_id  BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    cuenta_id   BIGINT REFERENCES cuentas_meli(id) ON DELETE SET NULL,
    accion      TEXT NOT NULL,
    detalle     JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip          TEXT,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario_id, creado_en DESC);

ALTER TABLE auditoria ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS auditoria_propia ON auditoria;
CREATE POLICY auditoria_propia ON auditoria
    USING (usuario_id = current_setting('app.usuario_actual')::bigint)
    WITH CHECK (usuario_id = current_setting('app.usuario_actual')::bigint);

GRANT SELECT, INSERT ON auditoria TO app_backend;
GRANT USAGE, SELECT ON auditoria_id_seq TO app_backend;

-- Mails que CoreLux le mandó a cada persona (cobro que no se pudo hacer, plan dado de baja, cambio de plan, fin de la prueba…).
-- Sirve para dos cosas: (1) que el mismo aviso no salga dos veces (UNIQUE por persona + tipo + clave: la clave identifica el hecho, p. ej. el día de cobro) y
-- (2) poder reconstruir «¿qué se le avisó y cuándo?». El aviso se reserva ANTES de mandarlo y se libera si el envío falla, así se reintenta en la próxima corrida.
-- Mientras no haya proveedor de mail configurado (CORREO_PROVEEDOR / CORREO_API_KEY / CORREO_REMITENTE) el módulo no escribe nada acá.

CREATE TABLE IF NOT EXISTS correos_enviados (
    id          BIGSERIAL PRIMARY KEY,
    usuario_id  BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo        TEXT NOT NULL,
    clave       TEXT NOT NULL DEFAULT '',
    destino     TEXT NOT NULL,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, tipo, clave)
);

ALTER TABLE correos_enviados ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS correos_enviados_propios ON correos_enviados;
CREATE POLICY correos_enviados_propios ON correos_enviados
    USING (usuario_id = current_setting('app.usuario_actual')::bigint)
    WITH CHECK (usuario_id = current_setting('app.usuario_actual')::bigint);

GRANT SELECT, INSERT, DELETE ON correos_enviados TO app_backend;
GRANT USAGE, SELECT ON correos_enviados_id_seq TO app_backend;

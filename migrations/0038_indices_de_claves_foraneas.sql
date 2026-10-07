-- Índices que faltaban en claves foráneas con borrado en cascada (o que se anula). Sin un índice en la columna de la tabla hija, borrar un usuario o una cuenta obliga a
-- recorrer esa tabla entera para encontrar sus filas. Se detectaron consultando pg_constraint contra pg_index (las 6 claves foráneas sin índice que respalde su columna).
-- (referrals.referred_id y referrals.referrer_id YA tienen índice: no se tocan.)
CREATE INDEX IF NOT EXISTS idx_feedback_usuario ON feedback (usuario_id);
CREATE INDEX IF NOT EXISTS idx_feedback_cuenta ON feedback (cuenta_id);
CREATE INDEX IF NOT EXISTS idx_alertas_usuario_cuenta ON alertas_usuario (cuenta_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_cuenta ON auditoria (cuenta_id);
CREATE INDEX IF NOT EXISTS idx_oauth_vinculaciones_usuario ON oauth_vinculaciones_pendientes (usuario_id);
CREATE INDEX IF NOT EXISTS idx_productos_padre_proveedor ON productos_padre (proveedor_id);

-- El índice de alertas sin leer llevaba `leida` entre sus columnas siendo que el WHERE ya fija leida = false: una columna constante que solo ocupaba lugar. Las consultas
-- (WHERE usuario_id = ... AND leida = false ORDER BY creada_en DESC) siguen usando el índice nuevo.
DROP INDEX IF EXISTS idx_alertas_usuario_no_leidas;
CREATE INDEX IF NOT EXISTS idx_alertas_usuario_no_leidas ON alertas_usuario (usuario_id, creada_en DESC) WHERE leida = false;

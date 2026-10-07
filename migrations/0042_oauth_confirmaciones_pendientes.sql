-- Confirmación antes de vincular otra cuenta de Mercado Libre desde un enlace que se abrió en OTRO navegador (migración 0013).
-- Ese enlace es una credencial: quien lo complete en Mercado Libre queda vinculado al usuario de CoreLux que lo generó. Para que nadie sea vinculado sin enterarse (el CSRF clásico de
-- OAuth: una persona arma su enlace y se lo hace completar a otra), después del login de Mercado Libre se muestra «¿Confirmás vincular @cuenta a la cuenta de CoreLux de a***@…?» y
-- la vinculación recién se hace al confirmar. Esta tabla guarda, por 10 minutos y CIFRADOS, los permisos que Mercado Libre acaba de dar mientras la persona decide.
-- Se lee y se escribe con la conexión de administración (en ese momento puede no haber ninguna sesión), igual que oauth_vinculaciones_pendientes: la seguridad la da el token de un
-- solo uso (aleatorio, 256 bits, vida corta) y no RLS; se habilita con una política abierta para que Supabase no la bloquee por su cuenta (ver el comentario de la 0013).
CREATE TABLE IF NOT EXISTS oauth_confirmaciones_pendientes (
    token                   TEXT PRIMARY KEY,
    usuario_id              BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    meli_user_id            BIGINT NOT NULL,
    nickname                TEXT,
    site_id                 TEXT,
    access_token_cifrado    TEXT NOT NULL,
    refresh_token_cifrado   TEXT NOT NULL,
    expires_in              INTEGER NOT NULL,
    creado_en               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_oauth_confirmaciones_usuario ON oauth_confirmaciones_pendientes (usuario_id);
GRANT SELECT, INSERT, DELETE ON oauth_confirmaciones_pendientes TO app_backend;
ALTER TABLE oauth_confirmaciones_pendientes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS oauth_confirmaciones_pendientes_acceso_backend ON oauth_confirmaciones_pendientes;
CREATE POLICY oauth_confirmaciones_pendientes_acceso_backend ON oauth_confirmaciones_pendientes USING (true) WITH CHECK (true);

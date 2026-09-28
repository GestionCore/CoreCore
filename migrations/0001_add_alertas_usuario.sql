-- Migración 0001: tabla alertas_usuario + columnas de racha en cuentas_meli
--
-- Esta migración es IDEMPOTENTE: usa IF NOT EXISTS y IF NOT EXISTS para
-- que pueda correrse más de una vez sin error (protección ante el caso en
-- que parte del SQL se aplicó manualmente en Supabase en sesiones anteriores).
--
-- TABLA alertas_usuario
-- ---------------------
-- Almacena notificaciones in-app generadas por el motor de alertas (Celery).
-- Ejemplos: token vencido, stock en quiebre inminente, reputación en riesgo.
-- El usuario las ve como un badge en el nav y puede marcarlas como leídas.
--
-- POLÍTICA RLS
-- ------------
-- Mismo patrón que el resto de las tablas: un usuario solo puede ver sus
-- propias alertas. La escritura viene del worker de Celery usando
-- db.conexion_usuario(usuario_id) — así RLS ya filtra correctamente.

-- 1) Tabla principal
CREATE TABLE IF NOT EXISTS alertas_usuario (
    id          BIGSERIAL       PRIMARY KEY,
    usuario_id  BIGINT          NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    cuenta_id   BIGINT          REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    tipo        TEXT            NOT NULL,
    titulo      TEXT            NOT NULL,
    mensaje     TEXT            NOT NULL,
    leida       BOOLEAN         NOT NULL DEFAULT false,
    accion_url  TEXT,
    creada_en   TIMESTAMPTZ     NOT NULL DEFAULT now(),
    leida_en    TIMESTAMPTZ
);

-- Índice para la query más común: alertas no leídas de un usuario
CREATE INDEX IF NOT EXISTS idx_alertas_usuario_no_leidas
    ON alertas_usuario (usuario_id, leida, creada_en DESC)
    WHERE leida = false;

-- 2) Row Level Security — mismo patrón que las demás tablas de la app
ALTER TABLE alertas_usuario ENABLE ROW LEVEL SECURITY;

-- DROP antes de recrear para que sea idempotente sin error de "already exists"
DROP POLICY IF EXISTS alertas_acceso_propio ON alertas_usuario;
CREATE POLICY alertas_acceso_propio ON alertas_usuario
    USING (
        usuario_id::text = current_setting('app.usuario_actual', true)
    );

-- GRANT explícito — sin esto, "permission denied for table alertas_usuario"
-- para el rol real de la app (mismo patrón encontrado en producción con
-- navegacion_visitas y tendencias_seguimiento: RLS no alcanza sin esto).
GRANT SELECT, INSERT, UPDATE, DELETE ON alertas_usuario TO app_backend;
GRANT USAGE, SELECT ON alertas_usuario_id_seq TO app_backend;

-- 3) Columnas de racha en cuentas_meli (pendientes de sesiones anteriores)
--    IF NOT EXISTS evita error si ya fueron aplicadas manualmente.
ALTER TABLE cuentas_meli
    ADD COLUMN IF NOT EXISTS racha_dias     INT  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS racha_ultimo_dia DATE;

-- 4) Columna origen en ventas (distingue ventas MeLi de ventas manuales)
ALTER TABLE ventas
    ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'meli';

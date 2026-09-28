-- Tracking de navegación por usuario, para poder marcar "MÁS USADO"
-- en el menú y en el tab-strip persistente sin adivinar.
--
-- Sin RLS a propósito: sigue el mismo criterio que `usuarios` y
-- `referrals` (tablas escopeadas por usuario_id, no por cuenta_id) —
-- toda consulta filtra explícitamente por usuario_id en el código,
-- así que una política de RLS acá sería redundante y (si quedara sin
-- policy en alguna tabla nueva) el riesgo real es bloquear todo por
-- accidente, no dejar pasar de más.

CREATE TABLE IF NOT EXISTS navegacion_visitas (
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nav_key         TEXT NOT NULL,
    contador        INTEGER NOT NULL DEFAULT 0,
    ultima_visita   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, nav_key)
);

-- Sin RLS (ver nota arriba), pero SÍ necesita GRANT explícito — el rol
-- que corre esta migración (app_admin o postgres, según cómo se aplique)
-- no es app_backend, así que sin esto la tabla queda creada pero
-- inaccesible para la app real ("permission denied for table
-- navegacion_visitas", encontrado en producción).
GRANT SELECT, INSERT, UPDATE, DELETE ON navegacion_visitas TO app_backend;

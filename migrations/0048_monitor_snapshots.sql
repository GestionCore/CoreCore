-- Monitor en vivo: los acumulados de HOY de publicidad y de visitas, anotados cada ~30 minutos.
--
-- Mercado Libre informa la publicidad (impresiones, clics, gasto, unidades) y las visitas POR DÍA, no por hora: se verificó contra la API real
-- (`aggregation_type` solo admite CAMPAIGN y DAILY; `unit=hour` se ignora y devuelve días). Pero SÍ da el acumulado del día en tiempo real. Para dibujar
-- las curvas por hora, CoreLux anota ese acumulado cada 30 minutos y la curva es la diferencia entre dos anotaciones seguidas.
--
-- tipo  = 'ads' (una fila por campaña, clave = id de la campaña) | 'visitas' (una fila por anotación, clave = '')
-- datos = {"impresiones", "clics", "costo", "unidades", "monto"} para ads; {"visitas"} para visitas (todo acumulado desde las 00:00 de Argentina)
-- Solo se usan las anotaciones de los últimos días: cada anotación nueva borra las de su cuenta con más de 3 días.

CREATE TABLE IF NOT EXISTS monitor_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    cuenta_id  BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    momento    TIMESTAMPTZ NOT NULL DEFAULT now(),
    tipo       TEXT NOT NULL,
    clave      TEXT NOT NULL DEFAULT '',
    datos      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_cuenta_momento ON monitor_snapshots(cuenta_id, momento);

ALTER TABLE monitor_snapshots ENABLE ROW LEVEL SECURITY;

-- Misma política que `ventas` (migración 0010): cuentas del usuario, y la cuenta activa cuando está seteada.
DROP POLICY IF EXISTS monitor_snapshots_por_cuenta_propia ON monitor_snapshots;
CREATE POLICY monitor_snapshots_por_cuenta_propia ON monitor_snapshots
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

GRANT SELECT, INSERT, DELETE ON monitor_snapshots TO app_backend;
GRANT USAGE, SELECT ON monitor_snapshots_id_seq TO app_backend;

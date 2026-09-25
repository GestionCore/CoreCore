-- Seguimiento de tendencias: términos o categorías que el usuario (o
-- CoreLux automáticamente, para la categoría principal detectada)
-- sigue en el tiempo. Mismo patrón que competidores_seguimiento /
-- competidores_historial — acá el objetivo es construir una curva
-- REAL de evolución (publicaciones, ventas de la muestra, precio
-- promedio) a partir de snapshots periódicos, no de un solo vistazo.
-- Arranca vacío para cada cuenta y se va llenando con el uso — nunca
-- se inventa un historial que no existe.

CREATE TABLE IF NOT EXISTS tendencias_seguimiento (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    tipo                TEXT NOT NULL CHECK (tipo IN ('termino', 'categoria')),
    valor               TEXT NOT NULL,          -- término de búsqueda libre, o category_id de MeLi
    etiqueta            TEXT NOT NULL,          -- nombre legible para mostrar
    automatico          BOOLEAN NOT NULL DEFAULT false,  -- true = la categoría principal detectada sola (no la siguió el usuario a mano)
    agregado_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cuenta_id, tipo, valor)
);
CREATE INDEX IF NOT EXISTS idx_tendencias_seg_cuenta ON tendencias_seguimiento(cuenta_id);

CREATE TABLE IF NOT EXISTS tendencias_snapshots (
    id                      BIGSERIAL PRIMARY KEY,
    cuenta_id               BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    seguimiento_id          BIGINT NOT NULL REFERENCES tendencias_seguimiento(id) ON DELETE CASCADE,
    fecha                   DATE NOT NULL,
    total_publicaciones     INTEGER,
    ventas_muestra          INTEGER,
    precio_promedio         NUMERIC(12,2),
    vendedores_distintos    INTEGER,
    UNIQUE (cuenta_id, seguimiento_id, fecha)
);
CREATE INDEX IF NOT EXISTS idx_tendencias_snap_seguimiento ON tendencias_snapshots(seguimiento_id);

ALTER TABLE tendencias_seguimiento ENABLE ROW LEVEL SECURITY;
ALTER TABLE tendencias_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY tendencias_seguimiento_por_cuenta_propia ON tendencias_seguimiento
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY tendencias_snapshots_por_cuenta_propia ON tendencias_snapshots
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

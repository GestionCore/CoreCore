-- Ventas cuya orden se canceló o se reembolsó DESPUÉS de haberse sincronizado.
--
-- El sync nunca guarda órdenes canceladas, pero una orden que estaba paga y se cancela días después (devolución, reembolso) seguía
-- en `ventas` para siempre y se contaba en facturación y ganancia. Ahora el sync las retira de `ventas`; acá queda la fila completa
-- tal como estaba (JSON), para poder auditarlas o restaurarlas. Mercado Libre conserva la orden con su estado.

CREATE TABLE IF NOT EXISTS ventas_retiradas (
    id           BIGSERIAL PRIMARY KEY,
    cuenta_id    BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_orden     TEXT NOT NULL,
    motivo       TEXT NOT NULL,
    monto        NUMERIC(14,2),
    fila         JSONB NOT NULL,
    retirada_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ventas_retiradas_cuenta ON ventas_retiradas(cuenta_id, id_orden);

ALTER TABLE ventas_retiradas ENABLE ROW LEVEL SECURITY;

-- Misma política que `ventas` (migración 0010): cuentas del usuario, y la cuenta activa cuando está seteada.
CREATE POLICY ventas_retiradas_por_cuenta_propia ON ventas_retiradas
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON ventas_retiradas TO app_backend;
GRANT USAGE, SELECT ON ventas_retiradas_id_seq TO app_backend;

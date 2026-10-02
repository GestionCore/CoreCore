-- Caché compartida por cuenta, en la base: sirve para lo que cuesta caro de calcular o de pedir (por ejemplo el mensaje del coach de IA).
--
-- Los cachés en memoria son por proceso: en producción hay 2 máquinas x 2 procesos, así que cada uno guardaba su propia copia (3 de cada 4 cargas
-- volvían a pedir lo mismo) y cada diccionario global es un riesgo de mezclar cuentas. Acá la clave incluye siempre la cuenta, y la política de RLS
-- impide leer la de otra.
--
-- firma: identifica el contenido del que depende el valor (si cambia, el valor guardado ya no vale). valor: {"v": ...}; "v" null = intento fallido.

CREATE TABLE IF NOT EXISTS cache_valores (
    cuenta_id       BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    clave           TEXT NOT NULL,
    firma           TEXT NOT NULL DEFAULT '',
    valor           JSONB NOT NULL,
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cuenta_id, clave)
);

ALTER TABLE cache_valores ENABLE ROW LEVEL SECURITY;

-- Misma política que `ventas` (migración 0010): cuentas del usuario, y la cuenta activa cuando está seteada.
DROP POLICY IF EXISTS cache_valores_por_cuenta_propia ON cache_valores;
CREATE POLICY cache_valores_por_cuenta_propia ON cache_valores
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON cache_valores TO app_backend;

-- Restituye el aislamiento por CUENTA ACTIVA en tendencias_seguimiento y tendencias_snapshots.
--
-- La migración 0010 dejó todas las tablas con cuenta_id filtrando por la cuenta elegida en sesión (app.cuenta_actual), además del usuario. Estas dos
-- se habían ajustado aparte; después la 0014 (un "re-arreglo" de permisos que recrea las políticas) las volvió a dejar solo por usuario: un usuario con
-- 2 cuentas (Plan Elite) veía las categorías seguidas de TODAS sus cuentas aunque estuviera mirando una sola. Se detectó al armar "Descargar mis datos":
-- la carpeta de una cuenta traía filas de la otra. La app ya filtraba por cuenta en sus consultas; esto devuelve la defensa a nivel de base.
--
-- Igual que en la 0010, la comparación va como TEXTO en los dos lados: castear un string vacío a bigint explota, y Postgres no garantiza cortar un OR en el
-- primer verdadero. Con cuenta_actual vacía o sin setear (call sites que todavía no pasan cuenta_id) se comporta como hasta ahora.
-- Se reafirman también los GRANT (mismo problema recurrente que documentan 0013 y 0014).

DROP POLICY IF EXISTS tendencias_seguimiento_por_cuenta_propia ON tendencias_seguimiento;
CREATE POLICY tendencias_seguimiento_por_cuenta_propia ON tendencias_seguimiento
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (current_setting('app.cuenta_actual', true) IS NULL OR current_setting('app.cuenta_actual', true) = '' OR cuenta_id::text = current_setting('app.cuenta_actual', true))
    );

DROP POLICY IF EXISTS tendencias_snapshots_por_cuenta_propia ON tendencias_snapshots;
CREATE POLICY tendencias_snapshots_por_cuenta_propia ON tendencias_snapshots
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (current_setting('app.cuenta_actual', true) IS NULL OR current_setting('app.cuenta_actual', true) = '' OR cuenta_id::text = current_setting('app.cuenta_actual', true))
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON tendencias_seguimiento TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON tendencias_snapshots TO app_backend;
GRANT USAGE, SELECT ON tendencias_seguimiento_id_seq TO app_backend;
GRANT USAGE, SELECT ON tendencias_snapshots_id_seq TO app_backend;

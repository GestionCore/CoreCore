-- La migración 0009 ya había dejado tendencias_seguimiento/tendencias_snapshots
-- con RLS + política por cuenta + GRANT a app_backend, y quedó registrada
-- como aplicada en schema_migrations — pero en producción volvió a
-- aparecer "permission denied for table tendencias_seguimiento" (Tendencias
-- daba 502). Mismo patrón que ya se documentó varias veces en este
-- proyecto (ver 0013 y el comentario del bug #8 en
-- schema/01_schema_multitenant.sql): algo del lado de Supabase (todo
-- indica que es su propio panel/advisor de seguridad) termina revocando
-- el GRANT o tocando la política después de que la migración original ya
-- corrió bien. Como 0009 ya está marcada como aplicada, migrate.py nunca
-- la iba a volver a correr sola — esta migración nueva reafirma
-- exactamente lo mismo, para que quede aplicada de nuevo sin tener que
-- tocar el historial de schema_migrations a mano.

ALTER TABLE tendencias_seguimiento ENABLE ROW LEVEL SECURITY;
ALTER TABLE tendencias_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tendencias_seguimiento_por_cuenta_propia ON tendencias_seguimiento;
CREATE POLICY tendencias_seguimiento_por_cuenta_propia ON tendencias_seguimiento
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

DROP POLICY IF EXISTS tendencias_snapshots_por_cuenta_propia ON tendencias_snapshots;
CREATE POLICY tendencias_snapshots_por_cuenta_propia ON tendencias_snapshots
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

GRANT SELECT, INSERT, UPDATE, DELETE ON tendencias_seguimiento TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON tendencias_snapshots TO app_backend;
GRANT USAGE, SELECT ON tendencias_seguimiento_id_seq TO app_backend;
GRANT USAGE, SELECT ON tendencias_snapshots_id_seq TO app_backend;

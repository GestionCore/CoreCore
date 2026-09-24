-- Grants para el panel de administración de CoreLux.
--
-- El rol app_admin (DATABASE_URL_ADMIN) necesita poder leer usuarios y
-- cuentas_meli para construir la vista del panel de admin, y actualizar
-- usuarios para cambiar plan/activo. Si DATABASE_URL_ADMIN usa la
-- service role key de Supabase, ya tiene acceso completo y este archivo
-- es idempotente (GRANT no falla si ya existe).
--
-- Si en cambio usás un rol personalizado con BYPASSRLS creado a mano,
-- corré esto para darle los permisos mínimos que necesita el panel.

DO $$
DECLARE
    role_name TEXT;
BEGIN
    -- Detectar el nombre del rol de la conexión admin (puede variar por entorno)
    SELECT current_user INTO role_name;
    -- Solo granteamos si no es el rol postgres/supabase superuser (que ya tiene todo)
    IF role_name NOT IN ('postgres', 'supabase_admin') THEN
        EXECUTE 'GRANT SELECT ON usuarios TO ' || quote_ident(role_name);
        EXECUTE 'GRANT UPDATE (plan, activo, actualizado_en) ON usuarios TO ' || quote_ident(role_name);
        EXECUTE 'GRANT SELECT ON cuentas_meli TO ' || quote_ident(role_name);
    END IF;
END
$$;

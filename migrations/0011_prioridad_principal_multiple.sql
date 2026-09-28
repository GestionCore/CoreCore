-- La pregunta "¿Qué es lo que más te importa controlar de tu negocio?"
-- del onboarding pasa a admitir elegir más de una opción (pedido
-- explícito — a diferencia de las otras 2 preguntas, que son de una
-- sola respuesta por naturaleza y no cambian). Se sigue guardando en
-- la misma columna `prioridad_principal`, ahora como texto separado
-- por comas ("ganancia,stock") en vez de un solo valor — así que el
-- CHECK de un solo valor de la lista tiene que salir.
--
-- Se busca el constraint por catálogo en vez de adivinar el nombre
-- (usuarios_prioridad_principal_check) porque Postgres solo lo nombra
-- así por default si nadie lo nombró a mano — más seguro no asumirlo.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
        WHERE rel.relname = 'usuarios' AND att.attname = 'prioridad_principal' AND con.contype = 'c'
    LOOP
        EXECUTE format('ALTER TABLE usuarios DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;

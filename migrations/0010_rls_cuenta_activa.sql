-- Defensa en profundidad para el aislamiento ENTRE LAS CUENTAS de un
-- mismo usuario (plan Elite, 2+ cuentas MeLi conectadas).
--
-- Hasta ahora, las políticas RLS de las tablas "hijas" (todo lo que
-- cuelga de una cuenta_id) solo filtraban por app.usuario_actual —
-- es decir, por CUALQUIER cuenta del usuario logueado, no por la
-- cuenta activa elegida en sesión (g.cuenta_id). Con un usuario de
-- una sola cuenta esto era invisible. La gran mayoría de las
-- consultas de solo-lectura del proyecto (dashboard, catálogo,
-- costos, chat IA, métricas de clientes, reporte fiscal, etc.) no
-- agregan un WHERE cuenta_id = %s explícito porque el diseño
-- buscado es "RLS ya lo resuelve" — así que apenas un usuario Elite
-- tenga 2+ cuentas conectadas, iba a ver datos MEZCLADOS de todas
-- sus cuentas en vez de solo la que eligió.
--
-- Esta limitación ya estaba documentada como conocida en
-- auth/registro.py (comentario en obtener_cuentas_de_usuario) desde
-- antes de que existiera ninguna pantalla que la disparara — quedó
-- sin aplicar a propósito hasta poder probarla a fondo. Verificado
-- en Supabase real antes de esta migración: 0 usuarios con 2+
-- cuentas conectadas hoy, así que no hay ningún dato en producción
-- que esta migración pueda "romper" de golpe.
--
-- Cómo funciona: db.py ahora también setea app.cuenta_actual (''
-- si no se pasa cuenta_id explícito). Cada política agrega un OR
-- que la deja pasar si esa variable está vacía/sin setear (mismo
-- comportamiento que antes, para cualquier call site que todavía
-- no pase cuenta_id) o si coincide con la cuenta_id de la fila. El
-- chequeo original (cuenta_id IN ... usuario_actual) se mantiene
-- intacto como capa de afuera — esto solo agrega una restricción
-- ADICIONAL, nunca la reemplaza.
--
-- cuentas_meli y meli_tokens NO se tocan: cuentas_meli necesita
-- mostrar TODAS las cuentas del usuario (para el selector de
-- cuenta), y meli_tokens ya bloquea todo acceso normal a propósito.
--
-- NOTA sobre ownership: esta migración cubre las 19 tablas originales
-- del esquema base, TODAS owned por el rol "postgres" (se crearon a
-- mano en el SQL Editor de Supabase) — por eso ALTER POLICY acá
-- necesita correrse logueado como owner ahí, no por migrate.py (el
-- rol app_admin no es owner de estas 19, aunque tenga BYPASSRLS).
-- tendencias_seguimiento y tendencias_snapshots (migración 0009) NO
-- están en este archivo: esas 2 las creó app_admin al correr 0009 por
-- migrate.py, así que quedaron owned por app_admin, no por postgres
-- — se aplicaron aparte, directo por migrate.py/conexion_admin, ya
-- verificado contra Supabase real (2026-09-27).
--
-- BUG real encontrado al probar esto YA APLICADO contra Supabase real
-- (no en la simulación previa, que no lo reproducía): Postgres NO
-- garantiza evaluar un OR de izquierda a derecha ni cortar en el
-- primer TRUE — así que "cuenta_id = current_setting(...)::bigint"
-- se evaluaba IGUAL aunque cuenta_actual fuera '', y castear '' a
-- bigint explota con "invalid input syntax for type bigint". Esto
-- rompía CUALQUIER query que no pasara cuenta_id (la mayoría del
-- proyecto todavía). Arreglado comparando como texto en los dos lados
-- (cuenta_id::text = cuenta_actual) en vez de castear el string vacío
-- a número — un bigint siempre castea a texto sin error, así que ya
-- no hay ninguna rama que pueda fallar.

ALTER POLICY ventas_por_cuenta_propia ON ventas
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY productos_padre_por_cuenta_propia ON productos_padre
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY productos_variantes_por_cuenta_propia ON productos_variantes
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY incidencias_posventa_por_cuenta_propia ON incidencias_posventa
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY gastos_operativos_por_cuenta_propia ON gastos_operativos
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY historial_precios_por_cuenta_propia ON historial_precios
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY historial_promociones_por_cuenta_propia ON historial_promociones
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY proveedores_por_cuenta_propia ON proveedores
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY competidores_seguimiento_por_cuenta_propia ON competidores_seguimiento
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY competidores_historial_por_cuenta_propia ON competidores_historial
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY tendencias_historial_por_cuenta_propia ON tendencias_historial
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY combos_sugeridos_por_cuenta_propia ON combos_sugeridos
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY logros_historial_por_cuenta_propia ON logros_historial
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY alertas_curva_talles_por_cuenta_propia ON alertas_curva_talles
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY alertas_quiebre_stock_por_cuenta_propia ON alertas_quiebre_stock
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY preguntas_pendientes_por_cuenta_propia ON preguntas_pendientes
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY comandos_pendientes_por_cuenta_propia ON comandos_pendientes
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY conversacion_whatsapp_por_cuenta_propia ON conversacion_whatsapp_historial
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

ALTER POLICY configuracion_cuenta_por_cuenta_propia ON configuracion_cuenta
    USING (
        cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint)
        AND (
            current_setting('app.cuenta_actual', true) IS NULL
            OR current_setting('app.cuenta_actual', true) = ''
            OR cuenta_id::text = current_setting('app.cuenta_actual', true)
        )
    );

-- tendencias_seguimiento y tendencias_snapshots: ver nota de ownership
-- más arriba — se aplicaron aparte, no van en este archivo.
--
-- El INSERT a schema_migrations NO va acá: esa tabla también la creó
-- app_admin (por migrate.py), no postgres — el rol del SQL Editor no
-- tiene permiso de escritura ahí. Supabase corre todo el pegado como
-- UNA transacción, así que si el INSERT fallaba al final, deshacía
-- las 19 ALTER POLICY de arriba también (pasó una vez). El registro
-- en schema_migrations se hace aparte, vía conexion_admin.

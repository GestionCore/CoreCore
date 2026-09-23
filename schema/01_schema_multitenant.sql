-- ============================================================================
-- ESQUEMA MULTI-TENANT — Integrador ML (PostgreSQL / Supabase)
-- ============================================================================
-- Decisiones de diseño clave:
--
-- 1. "usuarios" vs "cuentas_meli" están SEPARADAS a propósito. Un usuario
--    (quien paga la suscripción, con su login) puede tener MÁS DE UNA cuenta
--    de Mercado Libre conectada (pensando en el plan Elite / multi-cuenta,
--    como el caso real de Santi Mens + Noe Noe Indumentaria bajo un mismo
--    dueño). Todas las tablas de datos de negocio cuelgan de "cuenta_id"
--    (la cuenta de MeLi), NO de "usuario_id" directamente — porque los
--    datos (ventas, stock, etc.) pertenecen a LA CUENTA DE MELI, no a la
--    persona en sí.
--
-- 2. Todas las claves primarias pasan a ser "id BIGSERIAL" (surrogates
--    propios), en vez de usar el id_meli de MercadoLibre como clave — así
--    los JOIN son más simples y no dependemos de que MeLi nunca reutilice
--    un ID (cosa que en teoría no debería pasar, pero no vale la pena
--    apostar la integridad referencial a eso).
--
-- 3. CADA tabla de datos de negocio tiene su columna "cuenta_id" y una
--    política de Row Level Security (RLS) que la Postgres/Supabase hace
--    cumplir SOLA — así, aunque una consulta en el código se olvide del
--    WHERE cuenta_id = ..., la base de datos igual no va a devolver filas
--    de otra cuenta. Es la defensa real contra fuga de datos entre
--    usuarios, no solo la disciplina de quien escribe cada endpoint.
--
-- 4. Los tokens de acceso/refresh de MeLi NUNCA se guardan en texto plano
--    en una columna común — van encriptados a nivel de aplicación (con
--    una clave que vive en una variable de entorno, nunca en la base) o,
--    si preferís no tocar el código de encriptación ahora mismo, al menos
--    en una tabla separada con su propia política de RLS mucho más
--    restrictiva (ver sección 2).
-- ============================================================================


-- ============================================================================
-- SECCIÓN 1: USUARIOS Y CUENTAS DE MERCADO LIBRE (la raíz del multi-tenant)
-- ============================================================================

-- IMPORTANTE: esta tabla queda A PROPÓSITO sin Row Level Security. Es la
-- única tabla "raíz" — cuando alguien se loguea por primera vez, todavía
-- no existe ningún usuario_id contra el cual filtrar, así que no hay
-- nada que una política de RLS pueda comparar acá. El panel de Supabase
-- suele mostrar un aviso sugiriendo "activar RLS" en cada tabla nueva —
-- si lo activás en ESTA tabla en particular, el primer login de
-- cualquier cuenta nueva va a fallar con "new row violates row-level
-- security policy for table usuarios". Si ves ese error, la solución es:
--   ALTER TABLE usuarios DISABLE ROW LEVEL SECURITY;
CREATE TABLE usuarios (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    nombre          TEXT,
    -- Si el login de la app es "iniciá sesión con tu cuenta de MeLi"
    -- directamente (sin password propio), esta columna queda NULL. Si en
    -- algún momento sumás login con email+password propio además del de
    -- MeLi, acá va el hash (nunca la contraseña en texto plano).
    password_hash   TEXT,
    plan            TEXT NOT NULL DEFAULT 'trial' CHECK (plan IN ('trial', 'base', 'elite', 'cancelado')),
    trial_termina_en TIMESTAMPTZ,
    activo          BOOLEAN NOT NULL DEFAULT true,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Onboarding: encuesta de una sola vez la primera vez que alguien
    -- conecta su cuenta, para adaptar la experiencia a lo que realmente
    -- le importa en vez de mostrar lo mismo a todos por igual.
    onboarding_completo BOOLEAN NOT NULL DEFAULT false,
    prioridad_principal TEXT CHECK (prioridad_principal IN ('ganancia', 'stock', 'publicidad', 'competencia', 'todo')),
    experiencia_meli    TEXT CHECK (experiencia_meli IN ('nuevo', 'en_crecimiento', 'consolidado')),
    pantalla_preferida  TEXT CHECK (pantalla_preferida IN ('dashboard', 'stock', 'metricas'))
);

CREATE TABLE cuentas_meli (
    id                  BIGSERIAL PRIMARY KEY,
    usuario_id          BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    meli_user_id        BIGINT NOT NULL,          -- el "id" numérico que MeLi le da al vendedor
    nickname            TEXT,                      -- nickname de MeLi, solo para mostrar en la UI
    site_id             TEXT NOT NULL DEFAULT 'MLA',
    nombre_negocio      TEXT,                      -- ej: "Santi Mens" — para diferenciar cuentas en la UI si el usuario tiene varias
    activa              BOOLEAN NOT NULL DEFAULT true,
    conectada_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_sincronizacion TIMESTAMPTZ, -- último catálogo sincronizado con éxito
    ultima_sincronizacion_ventas TIMESTAMPTZ, -- hasta qué fecha ya trajimos órdenes reales de MeLi (para sincronizar incremental, no desde cero cada vez)
    sincronizacion_inicial_completa BOOLEAN NOT NULL DEFAULT false, -- se pone en true recién cuando la PRIMERA sincronización (catálogo + histórico de ventas) termina — mientras sea false, el frontend muestra la pantalla de "estamos trayendo tu información" en vez de páginas vacías
    racha_dias          INT NOT NULL DEFAULT 0,   -- días consecutivos usando la app (logros.py actualizar_racha)
    racha_ultimo_dia    DATE,                     -- último día (hora Argentina) que ya se contó, para no incrementar dos veces el mismo día
    UNIQUE (meli_user_id)  -- una misma cuenta de MeLi no puede quedar vinculada a dos usuarios nuestros a la vez
);

CREATE INDEX idx_cuentas_meli_usuario ON cuentas_meli(usuario_id);

-- Tokens de OAuth, en tabla separada de cuentas_meli a propósito — así la
-- política de RLS acá puede ser MÁS estricta todavía (ni siquiera el propio
-- usuario debería poder leer sus tokens crudos desde el cliente/frontend,
-- solo el backend con la service_role key de Supabase).
CREATE TABLE meli_tokens (
    cuenta_id           BIGINT PRIMARY KEY REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    access_token_cifrado    TEXT NOT NULL,   -- cifrado a nivel de aplicación, nunca texto plano
    refresh_token_cifrado   TEXT NOT NULL,
    expira_en           TIMESTAMPTZ NOT NULL,
    actualizado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ============================================================================
-- SECCIÓN 2: CATÁLOGO Y STOCK
-- ============================================================================

CREATE TABLE proveedores (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    nombre              TEXT NOT NULL,
    tiempo_entrega_dias INTEGER NOT NULL DEFAULT 7
);
CREATE INDEX idx_proveedores_cuenta ON proveedores(cuenta_id);

CREATE TABLE productos_padre (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli             TEXT NOT NULL,          -- el MLA... de la publicación
    titulo              TEXT,
    precio              NUMERIC(12,2),
    estado              TEXT,
    tipo_logistica      TEXT,
    precio_costo        NUMERIC(12,2) DEFAULT 0,
    thumbnail           TEXT,
    precio_original     NUMERIC(12,2),
    recibis_estimado    NUMERIC(12,2),
    cuotas_cantidad     INTEGER,
    cuotas_monto        NUMERIC(12,2),
    proveedor_id        BIGINT REFERENCES proveedores(id) ON DELETE SET NULL,
    UNIQUE (cuenta_id, id_meli)
);
CREATE INDEX idx_productos_padre_cuenta ON productos_padre(cuenta_id);
CREATE INDEX idx_productos_padre_estado ON productos_padre(cuenta_id, estado);

CREATE TABLE productos_variantes (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_variante         TEXT NOT NULL,          -- id de variante que da MeLi
    id_padre            BIGINT NOT NULL REFERENCES productos_padre(id) ON DELETE CASCADE,
    talle               TEXT,
    color               TEXT,
    stock_propio        INTEGER DEFAULT 0,
    stock_full          INTEGER DEFAULT 0,
    UNIQUE (cuenta_id, id_variante)
);
CREATE INDEX idx_variantes_cuenta ON productos_variantes(cuenta_id);
CREATE INDEX idx_variantes_padre ON productos_variantes(id_padre);


-- ============================================================================
-- SECCIÓN 3: VENTAS Y POSVENTA
-- ============================================================================

CREATE TABLE ventas (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_orden            TEXT NOT NULL,
    id_meli             TEXT NOT NULL,
    id_variante         TEXT,
    titulo              TEXT,
    cantidad            INTEGER NOT NULL DEFAULT 1,
    precio_venta        NUMERIC(12,2),
    cargo_venta         NUMERIC(12,2),
    costo_envio         NUMERIC(12,2),
    fecha_venta         DATE NOT NULL,
    hora_venta          TIME,
    impuestos           NUMERIC(12,2) DEFAULT 0,
    shipment_id         TEXT,
    envio_estado        TEXT,
    fecha_liberacion    DATE,
    monto_liberacion    NUMERIC(12,2),
    despachado          BOOLEAN NOT NULL DEFAULT false,
    comprador_nickname  TEXT,
    comprador_nombre    TEXT,
    origen              TEXT NOT NULL DEFAULT 'meli',  -- 'meli' | 'manual' (ventas_manuales.py — mostrador/canal directo)
    UNIQUE (cuenta_id, id_orden, id_meli)
);
CREATE INDEX idx_ventas_cuenta ON ventas(cuenta_id);
CREATE INDEX idx_ventas_cuenta_fecha ON ventas(cuenta_id, fecha_venta);
CREATE INDEX idx_ventas_id_meli ON ventas(cuenta_id, id_meli);
CREATE INDEX idx_ventas_liberacion ON ventas(cuenta_id, fecha_liberacion);

CREATE TABLE incidencias_posventa (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_reclamo          TEXT NOT NULL,
    id_orden            TEXT,
    tipo                TEXT,           -- 'return' | 'claim' | 'cancelacion'
    motivo              TEXT,
    estado              TEXT,
    monto_retenido      NUMERIC(12,2) DEFAULT 0,
    fecha               DATE,
    UNIQUE (cuenta_id, id_reclamo)
);
CREATE INDEX idx_incidencias_cuenta ON incidencias_posventa(cuenta_id);
CREATE INDEX idx_incidencias_fecha ON incidencias_posventa(cuenta_id, fecha);
CREATE INDEX idx_incidencias_orden ON incidencias_posventa(cuenta_id, id_orden);


-- ============================================================================
-- SECCIÓN 4: COSTOS, PRECIOS Y PROMOCIONES
-- ============================================================================

CREATE TABLE gastos_operativos (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    concepto            TEXT,
    categoria           TEXT,           -- 'fijo' | 'variable'
    monto               NUMERIC(12,2),
    fecha               DATE
);
CREATE INDEX idx_gastos_cuenta ON gastos_operativos(cuenta_id);

CREATE TABLE historial_precios (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli             TEXT NOT NULL,
    precio_anterior     NUMERIC(12,2),
    precio_nuevo        NUMERIC(12,2),
    fecha_cambio        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_historial_precios_cuenta ON historial_precios(cuenta_id);
CREATE INDEX idx_historial_precios_item ON historial_precios(cuenta_id, id_meli);

CREATE TABLE historial_promociones (
    id                      BIGSERIAL PRIMARY KEY,
    cuenta_id               BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli                 TEXT NOT NULL,
    titulo                  TEXT,
    precio_original         NUMERIC(12,2),
    precio_promo            NUMERIC(12,2),
    fecha_inicio            DATE,
    fecha_fin               DATE,
    fecha_fin_planeada      DATE,
    promedio_diario_previo  NUMERIC(10,2),
    activo                  BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX idx_promociones_cuenta ON historial_promociones(cuenta_id);


-- ============================================================================
-- SECCIÓN 5: COMPETENCIA, TENDENCIAS Y LOGROS
-- ============================================================================

CREATE TABLE competidores_seguimiento (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli_rival       TEXT NOT NULL,
    alias               TEXT,
    titulo_actual       TEXT,
    agregado_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cuenta_id, id_meli_rival)
);
CREATE INDEX idx_competidores_cuenta ON competidores_seguimiento(cuenta_id);

CREATE TABLE competidores_historial (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli_rival       TEXT NOT NULL,
    fecha               DATE NOT NULL,
    precio              NUMERIC(12,2),
    stock_disponible    INTEGER,
    es_full             BOOLEAN,
    sold_quantity       INTEGER,
    foto_principal_id   TEXT,
    UNIQUE (cuenta_id, id_meli_rival, fecha)
);
CREATE INDEX idx_competidores_hist_cuenta ON competidores_historial(cuenta_id);

CREATE TABLE tendencias_historial (
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    fecha               DATE NOT NULL,
    PRIMARY KEY (cuenta_id, keyword, fecha)
);

CREATE TABLE combos_sugeridos (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_meli_a           TEXT NOT NULL,
    id_meli_b           TEXT NOT NULL,
    veces_juntos        INTEGER DEFAULT 0,
    UNIQUE (cuenta_id, id_meli_a, id_meli_b)
);
CREATE INDEX idx_combos_cuenta ON combos_sugeridos(cuenta_id);

CREATE TABLE logros_historial (
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    mision_id           TEXT NOT NULL,
    titulo              TEXT,
    primera_vez_vista   DATE,
    ultima_vez_vista    DATE,
    resuelta            BOOLEAN NOT NULL DEFAULT false,
    fecha_resuelta      DATE,
    PRIMARY KEY (cuenta_id, mision_id)
);


-- ============================================================================
-- SECCIÓN 6: ALERTAS, PREGUNTAS Y COMANDOS DE WHATSAPP
-- ============================================================================
-- Importante: "comandos_pendientes" antes era una sola fila global
-- (clave='unico'). En multi-tenant, cada cuenta tiene la SUYA — por eso
-- ahora la clave primaria es cuenta_id directamente (una cuenta = un
-- comando pendiente de confirmación a la vez, que es la misma regla de
-- antes, solo que ahora aplicada por cuenta en vez de global).

CREATE TABLE alertas_curva_talles (
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    modelo_clave        TEXT NOT NULL,
    fecha_ultima_alerta TIMESTAMPTZ,
    PRIMARY KEY (cuenta_id, modelo_clave)
);

CREATE TABLE alertas_quiebre_stock (
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    id_variante         TEXT NOT NULL,
    fecha_ultima_alerta TIMESTAMPTZ,
    PRIMARY KEY (cuenta_id, id_variante)
);

CREATE TABLE preguntas_pendientes (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    question_id         TEXT NOT NULL,
    item_id             TEXT,
    texto_pregunta      TEXT,
    respuesta_sugerida  TEXT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado              TEXT NOT NULL DEFAULT 'pendiente',
    UNIQUE (cuenta_id, question_id)
);
CREATE INDEX idx_preguntas_cuenta ON preguntas_pendientes(cuenta_id, estado);

CREATE TABLE comandos_pendientes (
    cuenta_id           BIGINT PRIMARY KEY REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    comando             TEXT,
    parametros          JSONB,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversacion_whatsapp_historial (
    id                  BIGSERIAL PRIMARY KEY,
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    rol                 TEXT,
    texto               TEXT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversacion_cuenta ON conversacion_whatsapp_historial(cuenta_id, id);


-- ============================================================================
-- SECCIÓN 7: CONFIGURACIÓN POR CUENTA
-- ============================================================================

CREATE TABLE configuracion_cuenta (
    cuenta_id           BIGINT NOT NULL REFERENCES cuentas_meli(id) ON DELETE CASCADE,
    clave               TEXT NOT NULL,
    valor               TEXT,
    PRIMARY KEY (cuenta_id, clave)
);


-- ============================================================================
-- SECCIÓN 8: ROW LEVEL SECURITY — el corazón de la seguridad multi-tenant
-- ============================================================================
-- Esto asume que en el backend cada request, después de validar la sesión
-- del usuario, hace `SET app.cuenta_actual = '<id>'` (o el equivalente con
-- `set_config`) ANTES de correr cualquier consulta — así Postgres sabe
-- "para quién" está corriendo esa consulta y aplica el filtro solo.
-- Alternativa recomendada si usás Supabase Auth: usar `auth.uid()` en la
-- política, atando cuentas_meli.usuario_id al uid de Supabase Auth
-- directamente, en vez de una variable de sesión manual.

ALTER TABLE productos_padre ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos_variantes ENABLE ROW LEVEL SECURITY;
ALTER TABLE ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidencias_posventa ENABLE ROW LEVEL SECURITY;
ALTER TABLE gastos_operativos ENABLE ROW LEVEL SECURITY;
ALTER TABLE historial_precios ENABLE ROW LEVEL SECURITY;
ALTER TABLE historial_promociones ENABLE ROW LEVEL SECURITY;
ALTER TABLE proveedores ENABLE ROW LEVEL SECURITY;
ALTER TABLE competidores_seguimiento ENABLE ROW LEVEL SECURITY;
ALTER TABLE competidores_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE tendencias_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE combos_sugeridos ENABLE ROW LEVEL SECURITY;
ALTER TABLE logros_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE alertas_curva_talles ENABLE ROW LEVEL SECURITY;
ALTER TABLE alertas_quiebre_stock ENABLE ROW LEVEL SECURITY;
ALTER TABLE preguntas_pendientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE comandos_pendientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversacion_whatsapp_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE configuracion_cuenta ENABLE ROW LEVEL SECURITY;
ALTER TABLE meli_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE cuentas_meli ENABLE ROW LEVEL SECURITY;

-- Política genérica: solo se ven/tocan filas de cuentas que pertenecen
-- al usuario autenticado actual. Repetida para CADA tabla con
-- cuenta_id — antes esto quedaba como comentario "repetir para el
-- resto" sin estar realmente escrito, lo cual dejaba esas ~15 tablas
-- con RLS activado pero SIN ninguna política — en Postgres eso bloquea
-- TODO acceso por default, no lo deja abierto. Encontrado al probar un
-- INSERT real contra productos_padre.

CREATE POLICY ventas_por_cuenta_propia ON ventas
    USING (
        cuenta_id IN (
            SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint
        )
    );

CREATE POLICY productos_padre_por_cuenta_propia ON productos_padre
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY productos_variantes_por_cuenta_propia ON productos_variantes
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY incidencias_posventa_por_cuenta_propia ON incidencias_posventa
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY gastos_operativos_por_cuenta_propia ON gastos_operativos
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY historial_precios_por_cuenta_propia ON historial_precios
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY historial_promociones_por_cuenta_propia ON historial_promociones
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY proveedores_por_cuenta_propia ON proveedores
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY competidores_seguimiento_por_cuenta_propia ON competidores_seguimiento
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY competidores_historial_por_cuenta_propia ON competidores_historial
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY tendencias_historial_por_cuenta_propia ON tendencias_historial
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY combos_sugeridos_por_cuenta_propia ON combos_sugeridos
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY logros_historial_por_cuenta_propia ON logros_historial
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY alertas_curva_talles_por_cuenta_propia ON alertas_curva_talles
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY alertas_quiebre_stock_por_cuenta_propia ON alertas_quiebre_stock
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY preguntas_pendientes_por_cuenta_propia ON preguntas_pendientes
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY comandos_pendientes_por_cuenta_propia ON comandos_pendientes
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY conversacion_whatsapp_por_cuenta_propia ON conversacion_whatsapp_historial
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

CREATE POLICY configuracion_cuenta_por_cuenta_propia ON configuracion_cuenta
    USING (cuenta_id IN (SELECT id FROM cuentas_meli WHERE usuario_id = current_setting('app.usuario_actual')::bigint));

-- cuentas_meli tiene su propia política, comparando directo por usuario_id:
CREATE POLICY cuentas_propias ON cuentas_meli
    USING (usuario_id = current_setting('app.usuario_actual')::bigint);

-- meli_tokens: la política MÁS estricta — ni siquiera pensada para
-- consultarse desde el cliente/frontend, solo el backend (con la
-- service_role key de Supabase, que se salta RLS a propósito) debería
-- tocar esta tabla directamente.
CREATE POLICY tokens_solo_backend ON meli_tokens
    USING (false);  -- nadie autenticado como usuario normal puede leer esto directo; solo service_role

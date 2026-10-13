-- Fase 1 del pivot multi-rubro (docs/PIVOT_SAAS.md): el MERCADO es un dato global, no de cada cuenta.
--
-- Hasta ahora Tendencias guardaba un snapshot por cuenta (`tendencias_snapshots`): si 50 clientes seguían la misma categoría, el mismo dato se pedía a Mercado Libre y se
-- guardaba 50 veces (unas 25-35 llamadas cada vez). Estas tablas guardan UNA copia, que escribe un único trabajo del scheduler (con la conexión de administración) y que
-- cualquier cuenta lee. No llevan `cuenta_id` a propósito: son datos públicos de Mercado Libre, iguales para todos. El rol de la app solo puede LEER (nunca escribir).
--
-- Qué se verificó contra Mercado Libre real (sondeo del 2026-10-13, docs/SONDEO_FASE0.md) y condiciona el diseño:
--   · /trends/MLA/{categoría} devuelve entre 9 y 50 pares {keyword, url} SIN volumen: lo único medible es la POSICIÓN → se guarda como arreglo ordenado por día.
--   · /categories/{id} trae `total_items_in_this_category` (la serie de "tamaño de la oferta"); /products/search tiene un tope de 10.000 y no sirve para eso.
--   · /products/{id}/items NO trae sold_quantity ni available_quantity: no hay demanda de terceros, solo oferta (precio, envío, FULL, tienda oficial, descuento).
--   · Alcanza con un token de APLICACIÓN (client_credentials): nada de esto necesita el token de un cliente.
--
-- Sin particiones: ~2.000 categorías seguidas son ~730.000 filas por año (decenas de MB). Si algún día pasa de decenas de millones de filas, se parte por mes.

-- ── Árbol de categorías ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mercado_categorias (
    category_id      TEXT PRIMARY KEY,                       -- 'MLA1055'; 'MLA' es la lista general del sitio (ver el alta de abajo)
    nombre           TEXT NOT NULL,
    parent_id        TEXT,                                   -- sin FK: el árbol se carga por partes y Mercado Libre puede mover ramas
    camino           TEXT[] NOT NULL DEFAULT '{}',           -- ids desde la raíz hasta ella misma
    camino_nombres   TEXT[] NOT NULL DEFAULT '{}',
    dominio_id       TEXT,                                   -- 'MLA-CELLPHONES': el tipo de producto según Mercado Libre
    es_hoja          BOOLEAN,
    max_titulo       SMALLINT,                               -- settings.max_title_length (60 en casi todas, 200 en repuestos)
    max_variaciones  SMALLINT,                               -- settings.max_variations_allowed (100; 250 en ropa)
    publicaciones    INTEGER,                                -- último total conocido; la serie está en mercado_categoria_diaria
    seguida          BOOLEAN NOT NULL DEFAULT false,         -- entra al relevamiento diario cuando alguna cuenta vende ahí o la sigue
    ultimo_interes   DATE,                                   -- la última vez que una cuenta la vendió, la siguió o la miró; a los 90 días sin interés deja de seguirse
    actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mercado_categorias_parent ON mercado_categorias(parent_id);
CREATE INDEX IF NOT EXISTS idx_mercado_categorias_seguidas ON mercado_categorias(ultimo_interes) WHERE seguida;
CREATE INDEX IF NOT EXISTS idx_mercado_categorias_dominio ON mercado_categorias(dominio_id) WHERE dominio_id IS NOT NULL;

-- 'MLA' no es una categoría real: es la lista general de tendencias del sitio (`GET /trends/MLA`). Existe para poder guardar esa lista con la misma clave que las demás.
INSERT INTO mercado_categorias (category_id, nombre, camino, camino_nombres, es_hoja)
VALUES ('MLA', 'Todo Mercado Libre', ARRAY['MLA'], ARRAY['Todo Mercado Libre'], false)
ON CONFLICT (category_id) DO NOTHING;

-- ── Serie diaria por categoría ───────────────────────────────────────────────────────────────────────────────────────────────────────────
-- Una fila por categoría y día. `publicaciones` sale de una sola llamada barata y se guarda todos los días; el resto (la muestra de catálogo) cuesta ~25 llamadas y se toma
-- con menos frecuencia: las columnas de muestra quedan NULL los días que no se tomó. NULL = "ese día no se midió", nunca "cero".
CREATE TABLE IF NOT EXISTS mercado_categoria_diaria (
    category_id         TEXT NOT NULL REFERENCES mercado_categorias(category_id) ON DELETE CASCADE,
    fecha               DATE NOT NULL,
    publicaciones       INTEGER,
    muestra_productos   SMALLINT,                             -- productos de catálogo analizados
    muestra_ofertas     SMALLINT,                             -- publicaciones atadas a esos productos
    muestra_vendedores  SMALLINT,
    precio_min          NUMERIC(14,2),
    precio_p25          NUMERIC(14,2),
    precio_p50          NUMERIC(14,2),
    precio_p75          NUMERIC(14,2),
    precio_max          NUMERIC(14,2),
    pct_full            NUMERIC(4,1),
    pct_envio_gratis    NUMERIC(4,1),
    pct_tienda_oficial  NUMERIC(4,1),
    pct_con_descuento   NUMERIC(4,1),
    descuento_promedio  NUMERIC(4,1),
    concentracion_top3  NUMERIC(4,1),                         -- % de las ofertas de la muestra que tienen los 3 vendedores con más publicaciones
    hhi                 INTEGER,                              -- índice de Herfindahl-Hirschman de la muestra (0-10000)
    tomada_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category_id, fecha)
);

-- ── Búsquedas en alza: la posición es el único dato que Mercado Libre da (no hay volumen) ────────────────────────────────────────────────────
-- Diccionario de palabras: cada texto se guarda una sola vez y las series usan su id (4 bytes en vez de la palabra).
CREATE TABLE IF NOT EXISTS mercado_keywords (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    texto          TEXT NOT NULL UNIQUE CHECK (texto <> '' AND texto = lower(btrim(texto))),
    primera_vez    DATE NOT NULL DEFAULT CURRENT_DATE,
    -- Lo que Mercado Libre entiende de esa búsqueda (GET /sites/MLA/domain_discovery/search): categoría, dominio y los atributos que extrae ("iphone 15 128 gb" →
    -- Marca Apple, Línea iPhone 15, Memoria interna 128 GB). Se pide UNA vez por palabra y se guarda; NULL = todavía no se interpretó.
    categoria_id   TEXT,
    dominio_id     TEXT,
    atributos      JSONB NOT NULL DEFAULT '[]'::jsonb,
    interpretada_en TIMESTAMPTZ
);

-- La lista de cada categoría por día: `keywords` son ids de mercado_keywords y la POSICIÓN es el índice (el primero es el puesto 1). Un arreglo por día en vez de una fila por
-- palabra: 365 filas por categoría por año en vez de ~18.000. Integridad: no hay FK dentro de un arreglo; el trabajo del scheduler nunca borra palabras.
CREATE TABLE IF NOT EXISTS mercado_tendencias_diaria (
    category_id  TEXT NOT NULL REFERENCES mercado_categorias(category_id) ON DELETE CASCADE,
    fecha        DATE NOT NULL,
    keywords     INTEGER[] NOT NULL CHECK (cardinality(keywords) <= 100),
    tomada_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category_id, fecha)
);

-- Estado actual de cada palabra en cada categoría, que el trabajo diario actualiza de a un día. Las pantallas leen ESTO (una fila por palabra) y no recorren el historial:
-- "lleva 9 días seguidos", "subió 6 puestos en la semana", "entró hoy".
CREATE TABLE IF NOT EXISTS mercado_keyword_estado (
    category_id       TEXT NOT NULL REFERENCES mercado_categorias(category_id) ON DELETE CASCADE,
    keyword_id        INTEGER NOT NULL REFERENCES mercado_keywords(id) ON DELETE CASCADE,
    primera_vez       DATE NOT NULL,
    ultima_vez        DATE NOT NULL,
    racha_dias        INTEGER NOT NULL DEFAULT 1,             -- días seguidos en la lista hasta `ultima_vez`
    dias_en_lista     INTEGER NOT NULL DEFAULT 1,             -- días en total
    mejor_posicion    SMALLINT NOT NULL,
    posicion_actual   SMALLINT,                               -- NULL si hoy no está en la lista
    posicion_hace_7d  SMALLINT,
    PRIMARY KEY (category_id, keyword_id)
);
CREATE INDEX IF NOT EXISTS idx_mercado_keyword_estado_keyword ON mercado_keyword_estado(keyword_id);
CREATE INDEX IF NOT EXISTS idx_mercado_keyword_estado_vigentes ON mercado_keyword_estado(category_id, posicion_actual) WHERE posicion_actual IS NOT NULL;

-- ── Registro del relevador: qué corrió, cuánto costó y qué falló ─────────────────────────────────────────────────────────────────────────
-- Sirve para /admin/salud y para enterarse cuando Mercado Libre cierra un endpoint (ya cerró tres): un tipo de relevamiento que de golpe falla en todas las categorías.
CREATE TABLE IF NOT EXISTS mercado_relevamientos (
    id           BIGSERIAL PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('arbol', 'diario', 'muestra', 'palabras')),
    fecha        DATE NOT NULL,
    inicio       TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin          TIMESTAMPTZ,
    categorias   INTEGER NOT NULL DEFAULT 0,
    llamadas     INTEGER NOT NULL DEFAULT 0,
    errores      INTEGER NOT NULL DEFAULT 0,
    detalle      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_mercado_relevamientos_fecha ON mercado_relevamientos(fecha DESC, tipo);

-- ── Permisos: la app LEE; solo el trabajo de administración escribe ──────────────────────────────────────────────────────────────────────
ALTER TABLE mercado_categorias       ENABLE ROW LEVEL SECURITY;
ALTER TABLE mercado_categoria_diaria ENABLE ROW LEVEL SECURITY;
ALTER TABLE mercado_keywords         ENABLE ROW LEVEL SECURITY;
ALTER TABLE mercado_tendencias_diaria ENABLE ROW LEVEL SECURITY;
ALTER TABLE mercado_keyword_estado   ENABLE ROW LEVEL SECURITY;
ALTER TABLE mercado_relevamientos    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mercado_lectura ON mercado_categorias;
CREATE POLICY mercado_lectura ON mercado_categorias FOR SELECT TO app_backend USING (true);
DROP POLICY IF EXISTS mercado_lectura ON mercado_categoria_diaria;
CREATE POLICY mercado_lectura ON mercado_categoria_diaria FOR SELECT TO app_backend USING (true);
DROP POLICY IF EXISTS mercado_lectura ON mercado_keywords;
CREATE POLICY mercado_lectura ON mercado_keywords FOR SELECT TO app_backend USING (true);
DROP POLICY IF EXISTS mercado_lectura ON mercado_tendencias_diaria;
CREATE POLICY mercado_lectura ON mercado_tendencias_diaria FOR SELECT TO app_backend USING (true);
DROP POLICY IF EXISTS mercado_lectura ON mercado_keyword_estado;
CREATE POLICY mercado_lectura ON mercado_keyword_estado FOR SELECT TO app_backend USING (true);
DROP POLICY IF EXISTS mercado_lectura ON mercado_relevamientos;
CREATE POLICY mercado_lectura ON mercado_relevamientos FOR SELECT TO app_backend USING (true);

GRANT SELECT ON mercado_categorias, mercado_categoria_diaria, mercado_keywords, mercado_tendencias_diaria, mercado_keyword_estado, mercado_relevamientos TO app_backend;

COMMENT ON TABLE mercado_categorias IS 'Árbol de categorías de Mercado Libre (dato público, global). Escribe solo el relevador del scheduler.';
COMMENT ON TABLE mercado_categoria_diaria IS 'Serie diaria por categoría: tamaño de la oferta y, cuando se tomó, la muestra de catálogo. NULL = no se midió ese día.';
COMMENT ON TABLE mercado_tendencias_diaria IS 'Búsquedas en alza de cada categoría por día: arreglo de ids de mercado_keywords, la posición es el índice.';
COMMENT ON TABLE mercado_keyword_estado IS 'Estado actual de cada palabra por categoría (racha, mejor puesto, puesto de hace 7 días). Lo que leen las pantallas.';

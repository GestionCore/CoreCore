-- Fase 2 del pivot multi-rubro (docs/PIVOT_SAAS.md): la variante deja de ser «talle + color» y pasa a ser el conjunto de atributos que informa Mercado Libre; el costo
-- puede cargarse por variante y en dólares.
--
-- ADITIVA y por etapas: NO borra `talle` ni `color` (siguen escribiéndose mientras el código migra; una migración posterior las elimina cuando nada las lea).
-- Qué se verificó contra Mercado Libre real (sondeo del 2026-10-13, docs/SONDEO_FASE0.md):
--   · Las dimensiones de variación de un producto de catálogo son sus `pickers` (iPhone: COLOR, INTERNAL_MEMORY, RAM; pintura: COLOR, UNIT_VOLUME, UNITS_PER_PACK; herramientas: COLOR,
--     VOLTAGE; ropa: COLOR, talle). En una categoría, los atributos con la marca `allow_variations` son las dimensiones "de verdad" (celulares: solo COLOR; ropa: COLOR, SIZE…);
--     la marca `variation_attribute` también la llevan datos técnicos ocultos (PACKAGE_*, GTIN, MPN, SKU) que NO son variantes.
--   · Las 20 publicaciones de la cuenta de prueba traen SIZE, COLOR y family_id; ninguna tiene variaciones clásicas (cada talle/color es su propia publicación).
--   · `domain_id` ('MLA-CELLPHONES') identifica el rubro del producto sin mirar el título.
--
-- Bloqueo: ALTER TABLE pide un candado exclusivo sobre la tabla; si hay una consulta larga corriendo, falla a los 5 s en vez de dejar en cola a todo el que venga detrás.
SET LOCAL lock_timeout = '5s';

-- ── Variantes por atributos ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
-- `atributos`: lista de {id, name, value_id, value_name, value_struct?} tal como la informa Mercado Libre, SOLO los que definen la variante (no los técnicos).
-- `etiqueta`: texto para la pantalla que arma el sistema desde `atributos` ("128 GB / Azul", "4 L / Blanco", "M / Negro"); «Única» si no hay ninguno.
ALTER TABLE productos_variantes ADD COLUMN IF NOT EXISTS atributos JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE productos_variantes ADD COLUMN IF NOT EXISTS etiqueta TEXT;

-- ── Costo por variante y moneda del costo ────────────────────────────────────────────────────────────────────────────────────────────────
-- precio_costo de la variante: NULL = usa el costo de la publicación (`productos_padre.precio_costo`); con valor, manda sobre el de la publicación.
-- moneda_costo: 'ARS' o 'USD'. En la publicación siempre tiene valor (por defecto pesos); en la variante, NULL = la moneda de la publicación.
-- Los costos en dólares se convierten con la cotización del día (tabla `cotizaciones_dolar`); mientras nadie cargue uno en dólares, todo sigue como hasta hoy.
ALTER TABLE productos_variantes ADD COLUMN IF NOT EXISTS precio_costo NUMERIC(12,2);
ALTER TABLE productos_variantes ADD COLUMN IF NOT EXISTS moneda_costo TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS moneda_costo TEXT NOT NULL DEFAULT 'ARS';

ALTER TABLE productos_padre DROP CONSTRAINT IF EXISTS productos_padre_moneda_costo_valida;
ALTER TABLE productos_padre ADD CONSTRAINT productos_padre_moneda_costo_valida CHECK (moneda_costo IN ('ARS', 'USD'));
ALTER TABLE productos_variantes DROP CONSTRAINT IF EXISTS productos_variantes_moneda_costo_valida;
ALTER TABLE productos_variantes ADD CONSTRAINT productos_variantes_moneda_costo_valida CHECK (moneda_costo IS NULL OR moneda_costo IN ('ARS', 'USD'));
ALTER TABLE productos_variantes DROP CONSTRAINT IF EXISTS productos_variantes_precio_costo_no_negativo;
ALTER TABLE productos_variantes ADD CONSTRAINT productos_variantes_precio_costo_no_negativo CHECK (precio_costo IS NULL OR precio_costo >= 0);

-- ── Qué es cada publicación, sin mirar el título ─────────────────────────────────────────────────────────────────────────────────────────
-- domain_id: 'MLA-CELLPHONES', 'MLA-JACKETS_AND_COATS'… (viene en el ítem). atributos_clave: marca, modelo y GTIN ({"BRAND": "Apple", "MODEL": "iPhone 15", "GTIN": "…"}).
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS domain_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS atributos_clave JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ── Relleno de lo que ya existe, a partir de las columnas viejas ─────────────────────────────────────────────────────────────────────────
-- Para que las pantallas nuevas tengan etiqueta desde el primer día. La próxima sincronización con Mercado Libre reemplaza `atributos` por los datos reales (los de esta carga
-- llevan "origen": "legado" para poder contar cuántas faltan). Idempotente: solo toca las filas sin etiqueta.
UPDATE productos_variantes
SET atributos = (
        SELECT COALESCE(jsonb_agg(a), '[]'::jsonb) FROM (
            SELECT jsonb_build_object('id', 'SIZE', 'name', 'Talle', 'value_name', talle, 'origen', 'legado') AS a
            WHERE talle IS NOT NULL AND talle NOT IN ('', 'Único')
            UNION ALL
            SELECT jsonb_build_object('id', 'COLOR', 'name', 'Color', 'value_name', color, 'origen', 'legado')
            WHERE color IS NOT NULL AND color NOT IN ('', 'Único')
        ) x
    ),
    etiqueta = COALESCE(
        NULLIF(concat_ws(' / ', NULLIF(NULLIF(talle, ''), 'Único'), NULLIF(NULLIF(color, ''), 'Único')), ''),
        'Única'
    )
WHERE etiqueta IS NULL;

-- ── Cotización del dólar (global) ────────────────────────────────────────────────────────────────────────────────────────────────────────
-- Una fila por día y tipo de dólar, la escribe el scheduler (fuente libre: dolarapi.com, con bluelytics de respaldo; ambas respondieron en el sondeo). Se guarda la serie y no solo
-- el último valor para poder calcular el margen de una venta pasada con el dólar de ese día. 'bolsa' es el dólar MEP.
CREATE TABLE IF NOT EXISTS cotizaciones_dolar (
    fecha          DATE NOT NULL,
    casa           TEXT NOT NULL CHECK (casa IN ('oficial', 'blue', 'bolsa')),
    compra         NUMERIC(12,2),
    venta          NUMERIC(12,2) NOT NULL CHECK (venta > 0),
    fuente         TEXT NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha, casa)
);

ALTER TABLE cotizaciones_dolar ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cotizaciones_lectura ON cotizaciones_dolar;
CREATE POLICY cotizaciones_lectura ON cotizaciones_dolar FOR SELECT TO app_backend USING (true);
GRANT SELECT ON cotizaciones_dolar TO app_backend;

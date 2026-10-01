-- Qué usa cada cuenta y datos extra de cada publicación que ofrece la API de Mercado Libre.
--
-- CoreLux lo usan vendedores de cualquier rubro: lo que no aplica a una cuenta (Flex, FULL, catálogo, publicidad...) no se muestra.
-- cuentas_meli.capacidades: {"ads": true, "flex": false, "full": true, "catalogo": false, ...}, se refresca cada pocos días (capacidades.py).
--
-- productos_padre: se guardan campos del ítem que el sync de catálogo ya descarga y no guardaba (catalog_product_id, inventory_id,
-- permalink, category_id, listing_type_id) y se agregan los datos que se completan de a poco en segundo plano (enriquecimiento.py):
--   calidad_*   -> GET /item/{id}/performance (puntaje 0-100 y qué mejorar)
--   visitas_*   -> GET /items/{id}/visits/time_window (visitas de los últimos 14 días y de los 14 anteriores)
--   full_*      -> GET /inventories/{inventory_id}/stock/fulfillment (unidades no disponibles en FULL: dañadas, perdidas, en tránsito...)
--   catalogo_*  -> GET /items/{id}/price_to_win (solo publicaciones de catálogo: si ganan, comparten o pierden el primer lugar)

ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS capacidades JSONB;
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS capacidades_en TIMESTAMPTZ;

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS catalog_product_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS inventory_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS permalink TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS category_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS listing_type_id TEXT;

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS calidad_score SMALLINT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS calidad_nivel TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS calidad_acciones JSONB;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS calidad_en TIMESTAMPTZ;

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS visitas_14d INTEGER;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS visitas_previas_14d INTEGER;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS visitas_en TIMESTAMPTZ;

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS full_no_disponible INTEGER;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS full_detalle JSONB;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS full_en TIMESTAMPTZ;

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS catalogo_estado TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS catalogo_precio_para_ganar NUMERIC(12,2);
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS catalogo_en TIMESTAMPTZ;

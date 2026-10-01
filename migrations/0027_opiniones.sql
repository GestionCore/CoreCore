-- Opiniones de compradores (GET /reviews/item/{id}) y la clave que agrupa publicaciones que comparten opiniones.
--
-- family_id: Mercado Libre agrupa las publicaciones de un mismo modelo (por ejemplo, todos sus talles) en una familia y todas
-- comparten las opiniones. Sirve para no contarlas más de una vez y como clave de "modelo" que no depende del rubro ni del título.
-- user_product_id es distinto en cada variante (cada talle tiene el suyo).
-- opiniones_*: lo completa enriquecimiento.refrescar_opiniones en segundo plano; las pantallas leen de acá y no esperan a la API.

ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS user_product_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS family_id TEXT;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_promedio NUMERIC(3,2);
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_total INTEGER;
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_niveles JSONB;     -- {"1": n, "2": n, ... "5": n}
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_atributos JSONB;   -- [{"texto": "Al 86% le quedó como esperaba", "opciones": [{"nombre", "porcentaje"}]}]
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_criticas JSONB;    -- hasta 6 opiniones de 1 a 3 estrellas, las más recientes primero
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS opiniones_en TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_productos_padre_user_product ON productos_padre(cuenta_id, user_product_id);

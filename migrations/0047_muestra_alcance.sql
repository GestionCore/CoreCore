-- De dónde salen los precios de la muestra de una categoría (migración 0045: mercado_categoria_diaria).
--
-- Verificado contra Mercado Libre real (2026-10-13): en celulares, pintura y discos las ofertas de los productos de catálogo cuelgan de la categoría exacta; en herramientas (taladros) y
-- repuestos, no: un mismo tipo de producto («Taladros eléctricos») se publica en varias categorías hoja y la exacta quedaba sin ofertas. Cuando la categoría exacta trae muy pocas, la muestra
-- usa las ofertas de todo el DOMINIO del producto, y lo dice acá para que ninguna pantalla muestre ese precio como si fuera el de la categoría.
--   'categoria' = solo ofertas publicadas en esa categoría; 'dominio' = ofertas del mismo tipo de producto en cualquier categoría; NULL = fila sin muestra de precios.
ALTER TABLE mercado_categoria_diaria ADD COLUMN IF NOT EXISTS muestra_alcance TEXT;
ALTER TABLE mercado_categoria_diaria DROP CONSTRAINT IF EXISTS mercado_categoria_diaria_alcance_valido;
ALTER TABLE mercado_categoria_diaria ADD CONSTRAINT mercado_categoria_diaria_alcance_valido CHECK (muestra_alcance IS NULL OR muestra_alcance IN ('categoria', 'dominio'));

-- Las muestras ya guardadas (todas de la categoría exacta) quedan marcadas como tales.
UPDATE mercado_categoria_diaria SET muestra_alcance = 'categoria' WHERE muestra_ofertas IS NOT NULL AND muestra_alcance IS NULL;

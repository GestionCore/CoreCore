-- Una venta fuera de Mercado Libre puede descontar también el stock de la publicación en Mercado Libre (si no, la sincronización de cada 4 minutos
-- pisa el descuento local y MeLi sigue ofreciendo una unidad que ya no hay). Esta marca dice si se descontó allá, para devolverlo allá si la
-- venta se borra por error.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS stock_descontado_meli BOOLEAN NOT NULL DEFAULT false;

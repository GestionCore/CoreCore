-- Detalle completo de GET /items/{id}/price_to_win (version=v2): precio para ganar, estado, participación de visitas, competidores en el primer lugar,
-- y las condiciones («boosts»: envío gratis, cuotas, full…) con las que el ganador sostiene su precio. Una sola cifra no alcanza para describirlo.
-- catalogo_precio_para_ganar (NUMERIC) se conserva como el resumen que lee catalogo_ganar.py para cruzarlo con el precio mínimo.
-- Aditiva e idempotente: la tabla ya tiene sus políticas de RLS (por usuario y por cuenta activa), una columna nueva las hereda.
ALTER TABLE productos_padre ADD COLUMN IF NOT EXISTS catalogo_detalle JSONB;

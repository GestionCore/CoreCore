-- Si un reclamo/devolución cuenta contra la reputación del vendedor, según Mercado Libre
-- (GET /post-purchase/v1/claims/{id}/affects-reputation → "affected" | "not_affected" | ...).
-- Hasta ahora todo reclamo en mediación se mostraba como grave y restaba puntos de Salud aunque MeLi dijera que no afecta
-- la reputación (p. ej. los "no lo quiero" que pasan a mediación). NULL = todavía no se consultó: se trata como "podría afectar".
ALTER TABLE incidencias_posventa ADD COLUMN IF NOT EXISTS afecta_reputacion TEXT;

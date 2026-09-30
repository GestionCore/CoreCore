-- Reclamos y devoluciones: se guarda el código de motivo de Mercado Libre (reason_id, ej. PDD9939).
-- Hasta ahora solo se guardaba un texto traducido a mano, y esa traducción estaba mal (PDD9939 figuraba
-- como "Artículo no recibido" cuando es "arrepentimiento del comprador"). Con el código guardado el texto
-- oficial se puede regenerar siempre que haga falta, también para reclamos viejos ya cerrados.

ALTER TABLE incidencias_posventa ADD COLUMN IF NOT EXISTS reason_id TEXT;

-- Cantidad de cuotas con la que pagó el comprador — la API de Ordenes
-- de MeLi la trae en cada pago (orden.payments[].installments), pero
-- ventas_sync.py nunca la guardaba. Necesaria para el panel de
-- Clientes (cuotas vs. contado, desglose por cantidad de cuotas).
--
-- Ventas ya sincronizadas antes de esta migración quedan con
-- cuotas = NULL hasta que MeLi las vuelva a mandar en un sync futuro
-- (el sync es incremental, no reprocesa órdenes viejas) — el panel
-- las trata como "sin dato", no como "contado".

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cuotas INTEGER;

-- Provincia de destino del envío — para el ranking de "Ventas por
-- Provincia" del Dashboard. Sale de receiver_address.state.name en el
-- recurso /shipments/{id} que ventas_sync.py YA consulta para el costo
-- de envío (no agrega una llamada nueva a la API).
--
-- Igual que con `cuotas`: ventas ya sincronizadas quedan con
-- provincia = NULL hasta la próxima sincronización de esa orden.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS provincia TEXT;

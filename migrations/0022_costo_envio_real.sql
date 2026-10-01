-- Costo de envío REAL del vendedor, retenciones y lo que Mercado Libre depositó de verdad.
--
-- Hasta ahora ventas.costo_envio guardaba shipping_option.cost de /shipments/{id}: lo que paga el COMPRADOR (0 cuando
-- el envío es gratis). El costo que MeLi le cobra al vendedor está en GET /shipments/{id}/costs -> senders[0].cost
-- (FULL: ~15% de una venta de $55.000). Verificado contra el depósito real (GET /collections/{payment_id}.net_received_amount):
-- el modelo viejo sobrestimaba lo cobrado en ~15% de la facturación; con el envío real y las retenciones el desvío
-- bajó a ~1%. Ver flex.py y ventas_sync.py.
--
-- Un envío puede cubrir varias órdenes (packs): envio_shipment_total guarda el costo de TODO el envío (se repite en cada
-- fila) y costo_envio_meli la parte de esta fila, repartida por lo facturado. costo_envio = costo_envio_meli + costo_flex.
-- costo_envio_original conserva el valor anterior de cada fila corregida, por si hace falta revertir o auditar.
--
-- fecha_liberacion / monto_liberacion ya existían y nunca se llenaban (el ticker "Disponible mañana" mostraba siempre $0):
-- ahora salen del pago (money_release_date y net_received_amount).

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS envio_shipment_total NUMERIC(12,2);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS costo_envio_meli NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS costo_envio_original NUMERIC(12,2);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS retenciones NUMERIC(12,2);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS neto_recibido NUMERIC(12,2);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS pago_id BIGINT;

-- El panel de Despacho decidía si una venta era de FULL mirando el
-- tipo de logística CACHEADO en productos_padre (el estado actual de
-- la publicación) en vez del tipo de logística REAL de ese envío en
-- particular. Con "convivencia" (una publicación que vende a veces por
-- FULL y a veces por Flex/Correo según de dónde salga el stock) o
-- simplemente si la publicación cambió de modo después de la venta,
-- ese dato quedaba desactualizado — así aparecían ventas de FULL como
-- si fueran una tarea pendiente de despachar, cuando en realidad las
-- despacha MeLi solo.
--
-- Esta columna guarda el logistic_type real del envío, tal como lo
-- devuelve /shipments/{id} (mismo recurso que ventas_sync.py YA
-- consulta para el costo de envío — no agrega una llamada nueva). Las
-- ventas ya sincronizadas quedan con tipo_logistica = NULL hasta que
-- se vuelvan a sincronizar o hasta que Despacho las resuelva al vuelo.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS tipo_logistica TEXT;

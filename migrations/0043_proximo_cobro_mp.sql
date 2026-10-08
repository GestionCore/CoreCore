-- Día del próximo cobro de la suscripción de Mercado Pago del usuario (el `next_payment_date` que informa GET /preapproval/{id}).
-- El chequeo de renovaciones (renovaciones_mp.py) consulta a Mercado Pago SOLO cuando llega ese día, en vez de preguntar todos los días si sigue pago.
-- NULL = todavía no se sabe (se completa en la próxima revisión) o no tiene suscripción de Mercado Pago (cuentas de cortesía).
-- Aditiva e idempotente: la tabla `usuarios` ya tiene sus permisos.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS mp_proximo_cobro TIMESTAMPTZ;

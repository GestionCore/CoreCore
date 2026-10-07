-- Horario de corte de Correo (drop_off) de la cuenta: la semana completa que informa Mercado Libre en GET /users/{id}/shipping/schedule/drop_off, con la hora en que se
-- guardó ({"drop_off": {"monday": "13:00", ..., "saturday": null}, "actualizado_en": "..."}). Se refresca una vez por día al abrir Despacho (despacho_corte.py).
-- El corte de Flex NO va acá: la API no lo expone y lo carga la persona en Mi cuenta (configuracion_cuenta, clave `flex_hora_corte`).
-- Aditiva e idempotente: la tabla ya tiene sus políticas de RLS.
ALTER TABLE cuentas_meli ADD COLUMN IF NOT EXISTS horario_corte JSONB;

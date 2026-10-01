-- Cargo de financiación que paga el vendedor (charges_details "financing_add_on_fee", de collector a Mercado Libre): lo que cuesta
-- ofrecer cuotas. Ya está DENTRO de cargo_venta (viene en el sale_fee de la orden): esta columna solo lo separa para poder mostrarlo.
-- NULL = todavía no se consultó el pago; 0 = se consultó y no hubo cargo.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS financiacion NUMERIC(12,2);

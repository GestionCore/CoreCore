-- Cupones que financia el vendedor (cargo "coupon_fee" del pago, de collector a Mercado Libre). Es plata que MeLi descuenta de lo
-- depositado y no estaba en ningún costo. Los cupones que financia MeLi (coupon_rebate / coupon_code, de ml al comprador) no le
-- cuestan nada al vendedor y no se cuentan.
--
-- ventas.cargo_venta pasa a ser "todo lo que MeLi le cobra por la venta": comisión + financiación (sale_fee) + cupones. Así
-- Ganancia Real, Dashboard, Facturación y el reporte fiscal lo incluyen sin tocar cada cálculo. ventas.cupones guarda la parte de
-- cupones, para poder mostrarla y para que el sync no la pierda al reprocesar la orden (misma idea que costo_flex).

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cupones NUMERIC(12,2);

-- Mercado Libre informa las fechas de las órdenes con offset -04:00 aunque Argentina es UTC-3: hasta ahora se guardaba la hora "tal cual" (una hora
-- atrasada respecto de la hora argentina, y una venta de 00:30 caía en el día anterior). El sync nuevo convierte a hora argentina al ingresar y marca
-- cada fila que escribe con hora_normalizada = true. Las filas viejas quedan en false hasta que se corrijan con `python normalizar_horas.py --aplicar`
-- (que las desplaza una hora y las marca): la marca evita desplazar dos veces la misma fila.

ALTER TABLE ventas ADD COLUMN IF NOT EXISTS hora_normalizada BOOLEAN NOT NULL DEFAULT false;

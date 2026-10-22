# Propuesta: plazo de retención de los datos de compradores

Preparada el 2026-10-21. **Es una propuesta: no se cambió nada en la base ni en el código.** Anonimizar es irreversible, así que antes de hacerlo hace falta que el dueño elija los plazos.

## Por qué

La página oficial «Seguridad de aplicaciones» de Mercado Libre (23/06/2026) pide **minimización** (guardar solo lo estrictamente necesario), **retención limitada** (eliminar cuando ya no hace falta), cifrado en reposo de los datos personales (incluye la **dirección de envío**) y capacidad de eliminar a pedido. Los Términos (2.2.4 y 14) piden dejar de acceder a los datos de quien se va y destruir las copias, **sin fijar plazos**: el criterio de plazo lo tenemos que poner nosotros y poder justificarlo.

## Qué guardamos hoy de cada comprador (verificado en el código el 2026-10-21)

| Dato | Dónde | Quién lo lee hoy | Cuánto tiempo hace falta de verdad |
|---|---|---|---|
| Nombre (`comprador_nombre`) | `ventas`, `ventas_retiradas` (JSON) | Despacho (`_dia_despacho.html`): solo paquetes por entregar | Días, hasta despachar |
| Apodo (`comprador_nickname`) | `ventas`, `ventas_retiradas` | Despacho; «Ventas de hoy» (`ventas_hoy.py`); **clientes recurrentes** (`metricas.py:141`, cuenta órdenes por apodo) | Días para Despacho y Hoy; para «recurrentes» alcanza un identificador que no sea el apodo real |
| Coordenadas de destino (`destino_lat`, `destino_lon`) | `ventas` | Solo `flex.py` y `ventas_sync.py`: ubicar el envío en una zona de Flex y recalcular | Hasta asignar la zona (la zona queda guardada en `flex_zona`); para recalcular una venta vieja hace falta la localidad, no la coordenada exacta |
| Código postal y localidad | `ventas` | Flex (`flex.py`, `flex_zonas.py`) | Hasta asignar la zona; la provincia (más general) alcanza para las estadísticas |
| Provincia | `ventas` | Dashboard «ventas por provincia» | Es un dato general: se puede conservar |
| Nombre que escribe el vendedor en una venta manual | `ventas` (origen manual) | `ventas_manuales.html` | Es un dato que el propio vendedor carga: se queda y se borra con su cuenta |

**Discrepancia a corregir:** la política de privacidad (`templates/legal.html`, línea 77) dice que guardamos «apodo, nombre, y provincia y localidad de destino», pero el código guarda **además el código postal y las coordenadas** del destino. O se agregan al texto o se dejan de guardar las coordenadas.

Lo que ya está bien: la baja de cuenta (`/cuenta/eliminar`) borra todo en cascada; los webhooks se validan y se vuelven a consultar a Mercado Libre; no guardamos documentos, teléfonos, mails ni datos de pago de compradores.

## Propuesta (plazos a decidir)

1. **A los 90 días de la venta** (ya entregada o cerrada): `comprador_nombre` → vacío; `destino_lat/lon` → vacío; `comprador_nickname` → un **seudónimo estable** (hash con sal propia de cada cuenta) para que «clientes recurrentes» siga contando sin conservar el apodo real.
2. **A los 12 meses:** `codigo_postal` y `localidad` → vacío (queda la provincia). Las ventas ya valuadas por Flex conservan su zona (`flex_zona`); recalcular una venta de hace más de un año con «incluir ya valuadas» dejaría de poder reubicarla, y la zona guardada se mantiene.
3. Lo mismo, con las mismas claves, dentro del JSON de `ventas_retiradas.fila`.
4. **Copias de seguridad** (`respaldo.py` guarda un archivo por corrida y no borra los viejos): conservar los últimos N (propongo 8 semanales) y borrar el resto, y decirlo en la política («las copias de seguridad se eliminan a las 8 semanas»).
5. **Política de privacidad:** actualizar el texto (código postal, coordenadas, plazos, copias de seguridad) con el abogado.

## Cómo se haría (si se aprueba)

- Una tarea diaria del scheduler (como `_tarea_limpiar_soft_deletes`, `scheduler.py` ya está autorizado a usar `conexion_admin`), en lotes chicos para no trabar el pooler (15 conexiones).
- **Sin migración de esquema:** son `UPDATE` sobre columnas que ya existen.
- Primero una **vista previa** (cuántas filas se tocarían por cuenta) y recién después se activa; interruptor por variable de entorno para apagarla sin desplegar.
- Pruebas con la base real dentro de una transacción revertida: que anonimiza lo que debe, **no** toca facturación, ganancia, rankings por modelo ni ventas manuales, y que «clientes recurrentes» da el mismo número antes y después.
- Una prueba de guarda que falle si aparece un campo nuevo de comprador sin plazo.

## Lo que decide el dueño

1. ¿Plazos: 90 días y 12 meses, u otros?
2. ¿Se dejan de guardar las coordenadas exactas desde ahora (aunque se conserven 90 días las vigentes) o se actualiza la política?
3. ¿Se aprueba la rotación de copias de seguridad (8 semanales)?

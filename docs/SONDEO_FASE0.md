# Fase 0 del pivot multi-rubro: sondeo de endpoints de Mercado Libre

Hecho el 2026-10-13 con `sondeo_meli.py` (solo lectura), corrido en una máquina de producción de Fly con el token de la cuenta de prueba del dueño (`NOENOEINDUMENTARIA`). Total: 190 pedidos a Mercado Libre, ninguno modifica datos (el único POST pide el token de aplicación). No se imprimieron tokens ni datos personales. Una cuenta distinta de la de prueba podría ver otras respuestas en lo que depende de la cuenta (ver «Lo que sigue sin verificar»).

Cómo repetirlo (el script ya no está subido a la máquina):

```
fly ssh sftp put sondeo_meli.py /app/sondeo_meli.py -a corecore --machine <id>
fly ssh console -a corecore --machine <id> -C "sh -c 'cd /app && DB_POOL_MAX=1 python sondeo_meli.py <cuenta_id>'"     # o ... <cuenta_id> T7
fly ssh console -a corecore --machine <id> -C "rm /app/sondeo_meli.py"
```

Seis rubros probados, cada uno con su búsqueda: celulares (`iphone 15 128 gb`), herramientas (`taladro percutor bosch`), pintura (`pintura latex interior blanco 4 litros`), ropa (`campera de jean hombre`), discos (`disco solido ssd 1tb`) y repuestos (`pastillas de freno fiat palio`).

## Resultado resumido

| Rubro | Categoría (hoja) | Publicaciones | Búsquedas en alza | Productos de catálogo | De 6 productos, con ofertas |
|---|---|---:|---:|---:|---:|
| Celulares | MLA1055 | 116.579 | 50 | 10.000 (tope) | 6 |
| Herramientas | MLA5232 | 32.821 | 46 | 3.296 | 2 |
| Pintura | MLA413229 | 48.086 | 50 | 10.000 (tope) | 5 |
| Ropa | MLA109096 | 577.065 | **9** | 407 | 2 |
| Discos | MLA1672 | 45.458 | 49 | 4.714 | 2 |
| Repuestos | MLA61177 | 213.848 | 40 | 10.000 (tope) | **0** |

## Qué se confirmó (✅) y qué no existe (⛔)

1. ✅ **Token de aplicación.** `POST /oauth/token` con `grant_type=client_credentials` devuelve 200 (vence en 6 horas, `scope` amplio incluida escritura). Con ese token responden igual que con el de un cliente: `/trends/MLA[/{categoría}]`, `/sites/MLA/categories`, `/categories/{id}`, `/categories/{id}/attributes`, `/sites/MLA/domain_discovery/search`, `/products/search` y `/sites/MLA/listing_prices`. **Sin token**: `/trends`, `/sites/MLA/categories`, `/products/search` y `/listing_prices` dan 403 (`/categories/{id}` y `domain_discovery` sí abren). Conclusión: el relevador global usa el token de aplicación y no necesita rotar tokens de clientes. Como ese token puede escribir, se trata como secreto: se pide en cada corrida y no se guarda.
2. ✅ **`/trends/MLA/{categoría}`** devuelve entre 9 y 50 pares `{keyword, url}`. **No hay volumen**, ni fecha, ni variación: lo único medible es la posición y la permanencia. La categoría de ropa trae apenas 9 (las de electrónica y herramientas, 40 a 50).
3. ✅ **`/categories/{id}`**: `total_items_in_this_category` (la serie del tamaño de la oferta), camino desde la raíz y `settings`. `max_title_length` es 60 salvo repuestos (200). `max_variations_allowed` es 100, y 250 en ropa. `item_conditions` cambia por categoría (pintura y repuestos: solo nuevo).
4. ✅ **`/categories/{id}/attributes`** funciona (67 a 197 atributos). Dos marcas distintas:
   - `allow_variations`: las dimensiones de variación reales. Celulares: solo COLOR. Herramientas: COLOR y FREQUENCY. Pintura: COLOR y FINISH. Ropa: COLOR, SIZE y FABRIC_DESIGN. Discos: COLOR. Repuestos: ninguna.
   - `variation_attribute`: la llevan además datos técnicos que no son variantes (PACKAGE_HEIGHT, PACKAGE_WEIGHT, GTIN, AGID, MPN, SELLER_SKU, MAIN_COLOR…). **No sirve sola** para decidir qué es una variante.
5. ✅ **Los `pickers` de un producto de catálogo** (`GET /products/{id}`) son las dimensiones por las que se distinguen sus variantes: iPhone 15 → COLOR, INTERNAL_MEMORY, RAM; pintura → COLOR, UNIT_VOLUME, UNITS_PER_PACK (y FINISH); taladro → COLOR y VOLTAGE; disco → CAPACITY o COLOR; ropa → COLOR y talle del lote. Repuestos: ninguno (cada producto es una combinación auto/motor, p. ej. «Pastillas Freno Delanteras Fiat Palio 1.6 Spi»).
6. ✅ **`domain_discovery` extrae atributos de una búsqueda** (hoy se usaba solo para la categoría): «iphone 15 128 gb» → Marca Apple, Línea iPhone 15, Memoria interna 128 GB; «pintura latex interior blanco 4 litros» → Tipo Látex, Color Blanco, Volumen 4 L, Formato Unidad. Para ropa, herramientas y repuestos devolvió lista vacía. Una llamada por palabra, cacheable de por vida.
7. ✅ **`GET /products/{id}`** trae `attributes` completos (marca, modelo, RAM, capacidad, voltaje…), `pickers`, `family_name`, `parent_id`, `main_features`, `permalink`. `buy_box_winner` vino `null` en los 6 productos mirados (uno por rubro). `/reviews/item/{id de catálogo}` da 404.
8. ✅ **`GET /products/{id}/items`** (las ofertas de un producto) trae por oferta: precio, `original_price`, vendedor, `listing_type_id`, `condition`, `warranty`, `official_store_id`, `shipping` (envío gratis, `logistic_type` para FULL, costo), `seller_address` (provincia y ciudad), `sale_terms`, `tags`, `tier`, `inventory_id`, `user_product_id`, `min_purchase_unit`. Hasta 26 ofertas en un producto de celular.
9. ⛔ **No hay `sold_quantity` ni `available_quantity`** en ninguna de las ofertas de los 6 rubros. No existe demanda de terceros en la API: el panel de ventas de los clientes de CoreLux es la única fuente de demanda real (decisión 3).
10. ⛔ **Sigue cerrado**, probado con token de usuario y de aplicación: `/items/{id}` de otro vendedor (403 «Access to the requested resource is forbidden»; el multiget `/items?ids=` responde 200 pero con `code: 403` por cada ítem), sus visitas (403), `/users/{otro}/items/search` (403 «Searching another user items is restricted.»), `/sites/MLA/search` (cualquier combinación, 403) y `/highlights/MLA/category/{id}` (403).
11. ⚠️ **`/products/search` corta el total en 10.000.** Para el tamaño de la oferta se usa `total_items_in_this_category`, no ese paging.
12. ✅ **Fichas de dominio**: `GET /catalog_domains/MLA-CELLPHONES` (incluye `attributes`, `compatibilities`, `settings`) y `GET /domains/MLA-CELLPHONES/technical_specs` responden 200; `GET /domains/{id}` da 404. `HAS_COMPATIBILITIES` aparece como atributo de las categorías de los seis rubros.
13. ✅ **Publicaciones propias** (20 de la cuenta de prueba, en una sola llamada con `/items?ids=…&include_attributes=all`): las 20 traen `SIZE`, `COLOR` y `family_id`; ninguna tiene variaciones clásicas. El talle viene como «Único» o un número, y `FILTRABLE_SIZE` lista los talles del producto («XL,2XL,3XL,4XL»). El ítem de muestra trae `domain_id` (`MLA-SWEATSHIRTS_AND_HOODIES`).
14. ✅ **Sin cabeceras de límite de pedidos** en ninguna de las 190 respuestas (confirma lo que ya decía `meli_http.py`).
15. ✅ **Fuentes externas** (desde Fly): `dolarapi.com` (`/v1/dolares`: oficial 1.535, blue 1.550, bolsa/MEP 1.538,4 al momento del sondeo; 60 a 290 ms), `bluelytics` (725 ms) y la serie del IPC nacional en `apis.datos.gob.ar` (mensual, con unos dos meses y medio de atraso: el último dato era julio de 2026).

## Qué cambia en el diseño

- **Decisión 4 resuelta:** token de aplicación, sin fallback a tokens de clientes.
- **Variante = atributos de la publicación que coinciden con los de variación de su categoría (`allow_variations`) o con los `pickers` de su producto, menos los valores «Único»**; y, dentro de una misma `family_id`, los atributos cuyo valor cambia entre sus miembros. La marca `variation_attribute` se ignora por sí sola. En celulares la memoria interna es un `picker`, no una variación de la categoría: sin los `pickers` el 128 GB y el 256 GB no se distinguirían. Cuando no hay nada que distinga (repuestos), la etiqueta es «Única».
- **La cobertura de catálogo es muy desigual** (de 6 productos mirados: 6 en celulares, 5 en pintura, 2 en herramientas, discos y ropa, 0 en repuestos). Hay que mostrar siempre el tamaño de la muestra, y para repuestos apoyarse en las búsquedas en alza y el tamaño de la categoría, no en el muestreo de catálogo. Corrige la hipótesis del informe: no es cierto que «electrónica tenga buena cobertura» en general.
- **Relevamiento barato por categoría = 2 llamadas** (`/categories/{id}` y `/trends/MLA/{id}`); la muestra de catálogo cuesta unas 25 y se toma con menos frecuencia (las columnas quedan `NULL` los días que no se mide).
- **Cada palabra en alza se interpreta una sola vez** con `domain_discovery` y se guarda en `mercado_keywords.atributos`.
- **Nuevas medidas que sí existen:** reparto de las ofertas por provincia (`seller_address`), % de FULL (`logistic_type`), % de tienda oficial, % con descuento, tipo de publicación y garantía.

## Lo que sigue sin verificar

- Qué trae `compatibilities` en `/catalog_domains/{id}` y si sirve para repuestos (no se leyó su contenido).
- Para qué sirve el campo `tier` de las ofertas.
- Cada cuánto cambia la lista de `/trends` (hay que verlo con historia: es lo que va a mostrar el relevador).
- Los límites de pedidos del token de aplicación (no hay cabeceras: hay que medir con carga real).
- Una cuenta con publicaciones de catálogo o con variaciones clásicas (la de prueba no tiene ni lo uno ni lo otro): el relleno de atributos de variantes se escribió contra la documentación y las respuestas de arriba, no contra una publicación con variaciones.

# Pivot a SaaS multi-rubro + módulo Tendencias y Demanda

Informe del 2026-10-13. Referencia histórica: lo que se encontró, lo que se propuso y lo que decidió el dueño. El avance de cada fase queda en `PENDIENTES.md`.

Cómo leerlo: el informe se hizo leyendo el repo y probando dos funciones con títulos de otros rubros. Los endpoints de Mercado Libre no se pudieron probar en vivo desde la PC (las credenciales locales dan `invalid_client`). Etiquetas: ✅ ya se usa en producción · ❓ documentado, sin verificar · ⛔ cerrado por MeLi (403).

## Decisiones del dueño (2026-10-13)

| # | Tema | Decisión |
|---|---|---|
| 1 | Variantes | Aprobado el modelo genérico: `atributos JSONB` + etiqueta autogenerada. Se elimina `talle` y `color` como columnas fijas. |
| 2 | Costo por variación (P1-06) | Sí. `precio_costo` a nivel variante, opcional, con prioridad sobre el costo de la publicación. |
| 3 | Panel de demanda agregado | Aprobado, con anonimato N = 5. El dueño actualiza Términos y Privacidad. |
| 4 | Token del relevador global | Primero token de aplicación (`client_credentials`). Si MeLi lo rechaza por permisos o cuota: rotar entre los tokens de clientes activos, cuidando sus límites. **Resuelto por el sondeo del 2026-10-13: el token de aplicación alcanza para todos los endpoints de mercado; no hace falta el fallback** (ver `docs/SONDEO_FASE0.md`). |
| 5 | Curva de talles | Se saca. Se reemplaza por **Cobertura de variantes clave**: avisa cuando se queda sin stock la variante que aporta más del 30 % de las ventas de ese modelo (un buzo talle M o un disco de 1 TB). |
| 6 | Costo en dólares (P1-28) | Entra ahora. Columna `moneda_costo` (ARS/USD). El tipo de cambio se consulta a una API libre (dólar MEP/blue). |
| 7 | País | Solo Argentina (MLA). |

**Estado (2026-10-13):** Fase 0 hecha (`docs/SONDEO_FASE0.md`, `sondeo_meli.py`). Migraciones de las Fases 1 y 2 preparadas y probadas contra la base real dentro de una transacción revertida (`0045_mercado_global.sql`, `0046_variantes_atributos_y_costo.sql`, `tests/test_mercado_migraciones.py`); **todavía no aplicadas** (las aplica el próximo deploy). Correcciones del sondeo al informe de abajo: la cobertura de catálogo es muy desigual entre rubros (no es buena en general en electrónica; en repuestos es nula), `buy_box_winner` vino vacío, y las dimensiones de variante salen de `allow_variations` + los `pickers` del producto (la marca `variation_attribute` incluye datos técnicos).

Orden de ejecución: **Fase 0** sondeo de endpoints → **Fase 1** relevador global y tablas de mercado → **Fase 2** variantes JSONB y costo por variante → Fase 3 pantalla Mercado → Fase 4 panel de demanda → Fase 5 oportunidad, alertas y estacionalidad.

---

## Resumen

1. Lo que mueve la plata (ganancia real, cargos, envíos, Flex, facturación, Monotributo) no depende del rubro.
2. El sesgo de indumentaria está en cuatro lugares: el esquema de variantes (dos columnas fijas `talle` y `color`), la detección del talle por regex sobre el título, la clave de «modelo» armada con el título y la «curva de talles».
3. Defecto real, probado con las funciones del repo:

   | Título | `limpiar_titulo_modelo` | `extraer_talle` |
   |---|---|---|
   | Apple iPhone 14 | Apple iPhone | 14 |
   | Apple iPhone 15 | Apple iPhone | 15 |
   | Pintura Látex … 4 L | Pintura Látex … | L |
   | Pintura Látex … 20 L | Pintura Látex … | L |

   El iPhone 14 y el 15 quedarían como el mismo modelo en Dashboard, Costos, Stock masivo y rankings.
4. Tendencias hoy mide la **oferta**, no la **demanda**: `tendencias_snapshots.ventas_muestra` se guarda siempre en `None`.
5. `/trends` de MeLi da palabra y posición, sin volumen. «Volumen de búsquedas» no existe como dato.
6. La ventaja única de CoreLux es ser multi-cuenta: con las ventas reales de todos los clientes, anonimizadas, se arma un panel de demanda que nadie más tiene.

---

# PARTE 1 — Desvincular la indumentaria

Alcance medido: la palabra «talle» aparece en 22 módulos Python (120 veces, sin tests) y en 9 plantillas (21 veces); no aparece en el JS. `extraer_talle` y `limpiar_titulo_modelo` se llaman unas 27 veces en 15 módulos.

## A. Base de datos

- **P1-01 [Alta] Variantes con dos columnas fijas.** `productos_variantes.talle` y `.color`. Propuesta: `atributos JSONB` con las combinaciones tal como las informa MeLi (id, nombre, value_id, value_name y, si existe, valor numérico con unidad) + una `etiqueta` legible («128 GB / Azul», «4 L / Blanco») que arma el sistema. `talle` y `color` quedan como columnas derivadas mientras se migra y después se borran.
- **P1-02 [Alta] Quién lee `talle` y `color` hoy:** `analisis_stock.py:27`, `catalogo.py:28` (un `GROUP BY` por talle y color), `metricas.py:269`, `ventas_manuales.py:53`, `app.py:429` (exportación CSV), `sincronizador.py:246` y `utils.cuenta_usa_talles`.
- **P1-03 [Media] Faltan datos del producto en `productos_padre`.** Ya guarda `family_id`, `catalog_product_id`, `user_product_id`, `category_id`. Falta `domain_id` (el tipo de producto según MeLi) y un puñado de atributos fijos: marca, modelo y GTIN.
- **P1-04 [Media] Clave de «modelo» sin depender del título.** Orden: `family_id` → id del ítem si tiene variaciones clásicas → `catalog_product_id` → título como último recurso.
- **P1-05 [Media] `alertas_curva_talles` es una tabla muerta.** Nada la escribe; solo `resumen_semanal.py:39` la cuenta. Se borra con su política de RLS.
- **P1-06 [Alta] Costo distinto por variación.** En celulares con variaciones clásicas, 128 GB y 256 GB tienen costos muy distintos dentro de la misma publicación. `productos_variantes.precio_costo` opcional, con prioridad sobre el costo de la publicación. Toca unos 7 módulos de plata.
- **P1-07 [Baja] Etiqueta de venta que se pierde.** La venta arma «M / Negro» con un JOIN a la variante; si MeLi la borra, el rótulo histórico desaparece.

## B. Lógica de extracción: matar las regex del título

- **P1-08 [Alta] `utils.extraer_talle`** y sus tres regex. Reemplazo: `extraer_variantes(item, variacion)` que lee solo `attribute_combinations` y `attributes` de MeLi. Qué atributos son de variante lo decide MeLi por categoría (`GET /categories/{id}/attributes` ❓). Sin dato, la etiqueta es «Única», sin adivinar. Antes de borrar el regex hay que medir con la base real cuántas publicaciones viejas de ropa tienen el talle solo en el título.
- **P1-09 [Alta] `utils.limpiar_titulo_modelo`** es la fuente del defecto de los iPhone. La usan Despacho, Stock, Stock masivo, Catálogo, Dashboard, Tendencias, Costos y Análisis de stock. Pasa a ser el último recurso de P1-04.
- **P1-10 [Media] `sincronizador._extraer_talle_color`** busca por nombre en español («Talle», «Size», «Color») y no por id. Se guardan todas las combinaciones tal cual.
- **P1-11 [Media] `publicidad._RE_TALLE`:** regex duplicada. Se elimina.
- **P1-12 [Media] `analisis_stock.py:94`:** otra lectura del título; revisar junto con P1-08.
- **P1-13 [Media] `costos.py`:** `_PARECE_TALLE` y `nombres_de_variantes` adivinan variantes por palabras del título. Con atributos, el rótulo sale directo de ahí.
- **P1-14 [Media] `stock_masivo.ORDEN_LETRAS`:** ordena solo XS…XXXL. Orden genérico por valor numérico con unidad (`value_struct` ❓) y alfabético para el resto.
- **P1-15 [Baja] `meli_errores.py:24`:** diccionario fijo de nombres de atributos; usar el nombre que devuelve MeLi.

## C. Terminología y pantallas

- **P1-16 [Alta] El vocabulario es por cuenta, no por publicación.** `utils.vocabulario` y `cuenta_usa_talles` deciden «talle» o «variante» para toda la cuenta; una cuenta mixta se rompe. Debe resolverse por publicación o dominio, con el nombre de atributo que da MeLi.
- **P1-17 [Alta] «Talle» escrito en el HTML:** `costos.html` (4), `index.html` (4), `stock_masivo.html` (3), `calidad.html` (2), `dashboard_personalizable.html` (2), `metricas.html` (2), `landing.html` (2), `publicidad.html` (1), `_dia_despacho.html` (1).
- **P1-18 [Media] Tabla de Stock:** las columnas «Talle» y «Color» pasan a mostrar la etiqueta de variante.
- **P1-19 [Media] Exportaciones:** el CSV y el Excel de Métricas pasan a una columna «Variante» más una por atributo presente.
- **P1-20 [Media] Costos modelo → variante → talle:** el último nivel pasa a ser «variante» general.
- **P1-21 [Baja] Landing y onboarding:** ejemplos de varios rubros; no hace falta preguntar el rubro, sale de las categorías al sincronizar.

## D. Métricas y filtros que solo valen para ropa

- **P1-22 [Alta] Curva de talles.** `analisis_stock.evaluar_curva_talles` (M/L/XL fijos) y lo que cuelga: misiones de Logros y penalizaciones de Salud de cuenta. **Decidido: se elimina** y se reemplaza por *Cobertura de variantes clave* (variante que aporta > 30 % de las ventas del modelo y se queda sin stock).
- **P1-23 [Media] Ventana de rotación fija.** 14 días y alerta a ≤ 5 días; un vendedor de herramientas que vende 1 por mes aparece todo sin rotación. La ventana se adapta a la frecuencia de venta (30, 60 o 90 días).
- **P1-24 [Media] Motivos de devolución** con textos de ropa («Talle diferente al publicado»). Usar los textos de MeLi.
- **P1-25 [Media] Costos por chat:** ejemplos y singularización de ropa; el grupo también debe poder resolverse por marca o categoría.
- **P1-26 [Baja] IA:** el prompt de `app.py ~3180` dice «talle si aplica»; `chat_ia.py` y `calculadora_costos.py` tienen menciones menores.
- **P1-27 [Baja] Comentarios** de indumentaria en `monotributo.py:28`, `gunicorn.conf.py`, `precios.py`, `publicacion_edicion.py`.

## E. Supuestos que no son de rubro pero rompen el pivot

- **P1-28 [Media] Moneda.** `precio_costo` es solo en pesos. **Decidido: entra ahora** (`moneda_costo` ARS/USD, cotización de una API libre).
- **P1-29 [Media] País.** `"MLA"` fijo en 29 lugares de 13 módulos. **Decidido: solo Argentina por ahora.**
- **P1-30 [Baja] Tendencias elige una categoría arbitraria:** `obtener_categoria_principal` toma el primer producto activo sin ordenar.
- **P1-31 [Media] Sugerencia de título:** `cruzar_tendencias_con_catalogo` sugiere siempre sobre la primera publicación alfabética (`activos[0]`) y corta a 60 caracteres (límite que depende de la categoría).

---

# PARTE 2 — Tendencias y Demanda

## A. Lo que hay hoy y sus límites

- **Radar de tendencias** (`/trends/MLA/{categoría}`) ✅. El historial solo guarda «esta palabra apareció ese día», sin posición, y se borra a los 30 días.
- **Explorar mercado** ✅: catálogo, categorías y vendedores. Sin demanda real; la muestra son solo publicaciones atadas a productos de catálogo.
- **Seguimiento:** un snapshot diario por cuenta de publicaciones, precio mediano y vendedores. Se guarda **por cuenta**: si 50 clientes siguen la misma categoría, el mismo dato se calcula y se guarda 50 veces (unas 25–35 llamadas a MeLi cada vez).
- **Cachés en memoria por proceso** (4 copias en producción) de datos públicos; deberían ser una sola caché compartida.
- Hipótesis sin verificar: la cobertura de catálogo en celulares y electrónica es mucho mejor que en ropa, así que Tendencias funcionaría mejor ahí.

## B. Qué datos reales hay y cuáles no

| Dato | Endpoint | Estado |
|---|---|---|
| Búsquedas en alza (palabra y posición) | `GET /trends/MLA[/{categoría}]` | ✅ sin volumen |
| Árbol de categorías, total de publicaciones | `GET /categories/{id}`, `/sites/MLA/categories` | ✅ |
| Término → categoría | `GET /sites/MLA/domain_discovery/search` | ✅ |
| Productos de catálogo | `GET /products/search` | ✅ |
| Ofertas de un producto | `GET /products/{id}/items` | ✅ |
| Perfil público del vendedor | `GET /users/{id}` | ✅ |
| Comisiones por categoría | `GET /sites/MLA/listing_prices` | ✅ |
| Atributos de variación por categoría | `GET /categories/{id}/attributes` | ❓ |
| Detalle de producto de catálogo | `GET /products/{id}` | ❓ |
| `sold_quantity` de ofertas ajenas | `GET /products/{id}/items` | ❓ |
| Búsqueda general con ordenamiento | `GET /sites/MLA/search` | ⛔ |
| Más vendidos | `GET /highlights/...` | ⛔ |
| Detalle de publicaciones ajenas | `GET /items/{id}` ajeno | ⛔ |
| Token de aplicación | grant `client_credentials` | ❓ |
| Compatibilidades de repuestos | `/…compatibilities…` | ❓ |

No existe y no se inventa: el **volumen de búsquedas** (`/trends` da orden, no cantidad; se muestra posición, racha, sube/baja, entradas y salidas) y las **ventas de la competencia** (la única demanda real sale del panel de ventas de los clientes de CoreLux y, si el sondeo lo confirma, de `sold_quantity` en las ofertas de catálogo).

## C. Arquitectura de datos: historia sin reventar el almacenamiento

Principio: **el mercado es un dato global, no de cada cliente.**

1. **Tablas globales, sin `cuenta_id`**, solo lectura para el rol de la app, escritas por un único trabajo con lock de líder:
   - `mercado_categorias`: árbol de MeLi, una copia, refresco semanal.
   - `mercado_categoria_diaria`: una fila por categoría y día (publicaciones, vendedores, precio p25/p50/p75, % FULL, % envío gratis, % tienda oficial, concentración top 3).
   - `mercado_tendencias_diaria`: una fila por categoría y día con el top de palabras como **arreglo de ids** (la posición es el índice) y un diccionario `mercado_keywords(id, texto)`.
   - `mercado_keyword_estado`: estado actual de cada palabra (primera vez vista, racha, mejor posición, posición hace 7 días), actualizado de a un día. Las pantallas leen esto, no recorren el historial.
2. **Qué se sigue lo define el interés:** una categoría entra al relevamiento diario cuando algún cliente vende en ella o la sigue, y sale si nadie la mira en 90 días. El resto se consulta a pedido con caché de 6 a 24 h y no se guarda.
3. **Retención por capas:** detalle diario 90 días, resumen semanal hasta 2 años, mensual después. Con particiones mensuales, borrar lo viejo es borrar una partición (instantáneo, sin vacío).
4. **Panel de demanda propio:** un trabajo nocturno agrega las ventas de **todos** los clientes por categoría/dominio y día (unidades, órdenes, vendedores distintos, precio medio) en `panel_demanda_diaria`.
   - Anonimato: no se muestra ningún dato si lo aportan menos de **N = 5** vendedores.
   - Seguridad: función `SECURITY DEFINER` que solo devuelve agregados; nunca `conexion_admin`.
   - Legal: Términos y Privacidad (a cargo del dueño) y los términos de la API de MeLi sobre guardar y agregar datos.
   - Arranque lento: con pocos clientes por categoría muestra «sin datos suficientes»; no se rellena.

Tamaño estimado (a medir con datos reales): con ~2.000 categorías seguidas, `mercado_categoria_diaria` suma unos 730.000 filas por año, del orden de decenas de MB. Las tendencias de 500 categorías, con arreglo por día, unos pocos MB.

## D. KPIs de mercado

Cada KPI lleva una etiqueta visible: **Real** (dato directo de MeLi), **Derivado**, **Panel CoreLux** o **Estimado**.

1. Tamaño de la oferta: publicaciones activas y variación a 7/30/90 días. Real.
2. Saturación: publicaciones por vendedor y puesto frente a las categorías hermanas; con panel, publicaciones por unidad vendida. Derivado.
3. Concentración: % del top 3 e índice HHI sobre la muestra de catálogo (siempre con el tamaño de la muestra). Derivado.
4. Evolución de precios: mediana y rango p25–p75 por día. Real. Versión ajustada por inflación (IPC) y en dólares con fuentes externas.
5. Dispersión de precios. Derivado.
6. Logística del mercado: % FULL, envío gratis, tienda oficial, descuento promedio, con tendencia. Real.
7. Barrera de entrada: reputación y medalla de los vendedores top. Real.
8. Rotación de ofertas: publicaciones nuevas contra las que salieron por semana. Derivado.
9. Ranking de búsquedas: posición, racha, sube/baja, entradas y salidas. Real.
10. Estacionalidad: índice mensual y calendario (falta Hot Sale y Cyber Monday). Con 12 meses de historia; hasta entonces «juntando datos».
11. Demanda del panel CoreLux: unidades por día, ticket, tendencia, estacionalidad, con la cobertura a la vista («basado en N vendedores»).
12. Margen potencial: precio mediano − comisión real de la categoría − envío; con el costo del usuario, ganancia neta.
13. Oportunidad: puntaje con fórmula visible (demanda creciente, saturación baja, margen alto, precios dispersos), mostrando los componentes.
14. Atributos que dominan una categoría (128 GB frente a 256 GB): oferta real; con panel, demanda por atributo.
15. Cobertura de datos: cuánto del mercado vemos, siempre visible.

Dos niveles de lectura: para quien empieza, un semáforo, tres frases y una acción; para el experto, series con rango, comparación de categorías, filtros por atributo, alertas y descarga a Excel.

## E. Pantallas

Una sola sección **Mercado**: Radar, Categoría, Comparar, Estacionalidad, Oportunidades, Mis seguimientos y Alertas. Un botón principal por pantalla; componentes `ux-*` existentes.

## F. Riesgos

- Los endpoints se cierran (ya cerraron tres): cada KPI degrada con un cartel claro, no se rompe.
- Límite de llamadas: medir cuántas aguanta MeLi para un relevador global.
- La historia no se recupera: cada día sin guardar es un día perdido.
- El módulo no puede prometer «demanda» donde solo hay oferta.

---

# Orden de ejecución

- **Fase 0:** sondeo de endpoints (solo lectura, en Fly, con token real).
- **Fase 1:** relevador global y tablas de mercado (prenderlo primero para que la historia se vaya juntando).
- **Fase 2:** variantes por atributos + `precio_costo` y `moneda_costo`, en migración aditiva: primero se escribe en las dos formas, después se lee de la nueva y recién ahí se borran las regex y las columnas viejas. Independiente de la Fase 1.
- **Fase 3:** pantalla Mercado v1 con lo que ya existe.
- **Fase 4:** panel de demanda de CoreLux (requiere Términos actualizados).
- **Fase 5:** oportunidad, alertas y estacionalidad, cuando haya historia suficiente.

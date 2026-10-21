# Plan maestro de producto: Inteligencia de Mercado y Seguimiento de Competidores

Documento de producto del 2026-10-21. **No hay código en esta tanda**: es el plan para rehacer de cero el apartado de mercado (hoy: Mercado, Tendencias y Competencia, tres pantallas que se pisan). Parte de lo ya decidido en [`docs/PIVOT_SAAS.md`](PIVOT_SAAS.md) (multi-rubro, solo Argentina, panel de demanda con anonimato N = 5) y de lo ya verificado contra Mercado Libre en [`docs/SONDEO_FASE0.md`](SONDEO_FASE0.md).

**Cómo está armado.** Cada afirmación lleva una etiqueta de cuánto se sabe: ✅ **medido o verificado** (con la base real, el código o una prueba contra Mercado Libre) · 🔎 **dato de terceros** (sitio de la herramienta o un blog; sirve de pista, no de prueba) · ❓ **hipótesis a verificar** (hay un paso concreto para comprobarla en el Anexo A) · 💡 **propuesta**. Donde no hay dato, el plan lo dice; no se rellena.

---

## 0. Resumen en simple

1. **Qué vamos a hacer:** un módulo «Mercado» que responda tres preguntas de un vendedor de Mercado Libre: **¿qué me conviene vender?** (nichos), **¿qué hace mi competencia?** (competidores y publicaciones) y **¿hacia dónde va mi rubro?** (categorías).
2. **Lo que nos diferencia de Nubimetrics y compañía:** ellos muestran el mercado; nosotros lo cruzamos con **tu plata real**. Cada oportunidad se calcula con tu costo, tu comisión real, tu logística (FULL, Flex), tu dólar y tu margen mínimo. Ninguna herramienta que conocemos hace eso (🔎 una fuente rival dice que Nubimetrics no sincroniza las ventas ni la publicidad propias; no lo pudimos confirmar en su sitio).
3. **La limitación que no se puede negar:** Mercado Libre **no deja ver ventas, visitas ni stock de otros vendedores**, ni la búsqueda general (✅ verificado: 403). No vamos a prometer «ventas exactas de la competencia». Vamos a ofrecer lo que sí se puede medir, con la fuente y la confianza a la vista, y a **cavar un foso propio** con datos que nadie más tiene (ventas reales anonimizadas de nuestros clientes, costos de envío reales, precios de venta reales).
4. **Tres hallazgos de esta noche que cambian el plan** (✅ medidos en nuestra base y código):
   - Las búsquedas en alza de Mercado Libre **cambian una vez por semana** (273 de 296 pares de días consecutivos son idénticos) y la lista de 50 palabras **no es un ranking único**: las primeras 10 rotan (7 % de salidas por día) y las otras 40 casi no se mueven. Es coherente con 🔎 «10 de mayor crecimiento + 20 populares + 20 más deseadas tras buscar». Hoy mostramos «sube 3 puestos» como si fuera un ranking continuo: puede confundir.
   - **Hoy no hay precios de mercado**: de 39 categorías seguidas, 33 nunca tuvieron muestra de catálogo y las 6 que la tuvieron dieron 0 ofertas. Las **275 publicaciones del dueño tienen 0 productos de catálogo** (ropa casi no tiene). Todo lo que dependa de «precios de la competencia vía catálogo» funciona en celulares o pintura y **no en indumentaria**.
   - **El foso hoy está casi vacío**: 1 usuario, 2 cuentas de Mercado Libre, 9 días de historia de mercado. Con N = 5 por categoría, el panel de demanda **no muestra nada** todavía. El plan lo trata como una carrera de largo plazo y arma lo que sirve **mientras tanto**.
5. **Cómo sorteamos la opacidad (cinco palancas):** (1) lo público que sí hay (categorías, tendencias, ofertas de catálogo, perfil y reputación de cualquier vendedor); (2) **observar todos los días** y guardar la historia (la historia no se recupera); (3) estimar **órdenes por vendedor** con la variación de su contador público de transacciones, calibrado con nuestras propias cuentas; (4) el **panel CoreLux** de ventas anonimizadas; (5) **dato propio como verdad de referencia** (nuestras 2 cuentas con un año de órdenes).
6. **Cómo se usa:** un modo **Guía** (para quien empieza: 3 preguntas, 5 nichos con semáforo y «qué necesitás para entrar»), un modo **Seguimiento** (para quien ya vende: cómo voy contra el mercado y qué hago esta semana) y un modo **Analista** (tablas, filtros, series, comparaciones, exportación y tablero multi-cuenta).
7. **Orden propuesto:** primero **verificar** (un sondeo de lectura de 12 preguntas, 1 día), después **arreglar la base de datos de mercado** (muestreo, semanas, vendedores), después Radar + Nichos, Competidores, Mapa de categorías, Panel y Analista. Detalle y criterios de salida en la sección 11.
8. **Lo que necesito de vos:** 8 decisiones, al final (sección 15). Las dos que más pesan: autorizar el sondeo de verificación y definir cómo arrancamos el panel (invitar a 20–30 vendedores «pioneros»).

---

## 1. Punto de partida: qué hay hoy (medido el 2026-10-21)

| Pieza | Qué hace hoy | Estado real |
|---|---|---|
| **Mercado** (`mercado.py`, `/mercado`) | Lee las tablas globales `mercado_*`: búsquedas en alza de las categorías de la cuenta, oferta y su variación, comparación de categorías | ✅ Funciona y es honesto («sin dato» no es cero), pero **le faltan los precios** y trata la posición de la lista como ranking único |
| **Relevador global** (`mercado_relevador.py`) | Cada día, con token de aplicación: oferta por categoría + búsquedas en alza; cada 7 días, una muestra de catálogo (precios, FULL, envío gratis, concentración) | ✅ 39 categorías seguidas, 342 filas diarias desde el 2026-10-13, 1.769 palabras interpretadas, **0 errores en las últimas 6 corridas**, 77 a 377 llamadas por día. ⚠️ La muestra solo se toma en categorías **hoja** con dominio: **33 de 39 nunca** la tuvieron y las 6 que sí, trajeron 0 ofertas |
| **Tendencias** (`tendencias.py`, 1.100 líneas) | Radar por cuenta, explorador de términos y categorías **en vivo** (25–35 llamadas cada vez), score de SEO, calendario comercial | Pesada, con datos por cuenta que deberían ser globales; mucho se pisa con Mercado |
| **Competencia / Espía** (`espia_competencia.py`) | Sigue **productos de catálogo** que la persona carga pegando un link; guarda cada día cuántas ofertas y vendedores hay y cómo se reparte el precio | ✅ **0 seguimientos cargados** en las dos cuentas y 0 filas de historial: nadie la usa. Además solo sirve donde hay catálogo |
| **Catálogo para ganar** (`catalogo_ganar.py`) | Precio para ganar el puesto principal de **tus** publicaciones de catálogo (`price_to_win`, dato real propio) | ✅ Solo para quien tiene catálogo (el dueño no) |
| **Panel de demanda** | Diseñado, **no construido**; falta actualizar Términos y Privacidad | ❌ Con 2 cuentas ninguna categoría llega a N = 5 |

**Lo que sí tenemos y vale oro:** 2.851 órdenes de un año (2025-10 a 2026-10) de dos cuentas reales, con provincia, logística, costo de envío real, cargos reales, y los 275 productos con `family_id`, `domain_id` y atributos. Es la **verdad de referencia** para calibrar cualquier estimación.

---

## 2. Benchmark: Nubimetrics, Real Trends, Crystal Zoom

> Fuentes: los sitios públicos de cada herramienta (🔎 lo que ellas dicen de sí mismas, no auditado) y comparativos de terceros (🔎 con interés comercial). **No tuvimos acceso a sus productos ni a sus precios**, así que no se comparan precios ni exactitud.

### Nubimetrics (🔎 `nubimetrics.com`)
Tres módulos: **Mercado** («descubrir productos rentables»), **Competencia** y **Mi negocio**; además «Nubimetrics Enterprise» y un «Conector MCP» (sin descripción). Lo que dice su propio sitio:
- **Mercado:** detectar categorías con **alto crecimiento y poca saturación de vendedores** («Desembarca en una nueva categoría»); **palabras más buscadas del mes por categoría, con su facturación y unidades vendidas**; oferta por palabra clave (vendedores, procedencia, precio promedio, posicionamiento); **participación de cada categoría en las ventas y su crecimiento mensual**; concentración de vendedores profesionales y evolución del precio promedio; **mejores vendedores y tiendas oficiales de cada categoría con sus ventas mensuales y tu posición frente a ellos**; **picos de venta por categoría** («¿Cuándo se vende?»); **«Productos perfectos»** (mucha demanda de compradores, pocos vendedores).
- **Competencia:** comparar en simultáneo vendedores y tiendas oficiales por subcategoría con **ventas en dinero, unidades, visitas y conversión**; historial de cambios de sus publicaciones, publicaciones estrella, ticket promedio, incidencia de envío gratis, tipo de destaque, ventas con descuento; ranking en todas sus subcategorías; detección de nuevos jugadores; comparación de tus publicaciones con las suyas, incluidos cambios de precio.
- 🔎 Un testimonio dice que da historia **desde 2016**. Un competidor suyo dice que no sincroniza ventas ni publicidad propias del vendedor y que es caro (interés comercial: no se toma como hecho).

**Lectura para nosotros:** muestra **ventas, unidades, visitas y conversión de terceros**. Con la API pública abierta eso es **imposible** (✅ verificado por nosotros: `/items` ajeno, visitas ajenas y búsqueda general dan 403). Su fuente tiene que ser otra (un acuerdo con Mercado Libre, un panel propio, datos comprados o estimaciones): **no lo sabemos y no se puede copiar**. Tampoco tenemos su historia de 2016. Perder esa pelea de frente es seguro; hay que jugar otra.

### Real Trends (🔎 sitio institucional citado por argentina.gob.ar y fichas de startups)
Plataforma de Buenos Aires (2014; Argentina, Brasil y México), «**certificada por Mercado Libre**», dice más de 15.000 vendedores, web y móvil. Ofrece «herramientas de análisis y gestión»: métricas en tiempo real de lo que ocurre en Mercado Libre, análisis de mercado y competencia, paneles, **gestión y automatización de publicaciones, preguntas y ventas** y **multicuenta**. No pudimos ver el detalle de su análisis de mercado (el sitio no lo muestra) ni sus precios. (Ojo: `realtrends.com` es otra empresa, de bienes raíces en EE. UU.)

**Lectura:** su fuerte es la **gestión** (stock, preguntas, automatización) con análisis como complemento; la «certificación» sugiere acceso privilegiado a datos. Se parece más a CoreLux en conjunto que Nubimetrics, y valida que **multicuenta + análisis** es una combinación que se vende.

### Crystal Zoom (🔎 `crystalzoom.com`)
**No es una herramienta de inteligencia de mercado.** Según su propio sitio: compra el inventario del vendedor y **opera su marca** en Mercado Libre y Amazon (logística, gestión de distribuidores, publicidad, **automatización de precios y de catálogos** «para ganar catálogos, ajustar precios y mejorar márgenes», auditorías automáticas de precios, contenido y SEO). Menciona un «Control de Competidores» sin explicarlo. (Notas de prensa de 2020 lo describen como plataforma de publicidad patrocinada.)

**Lectura:** el aprendizaje no es de análisis sino de **acción**: pasar de «mirar al competidor» a «reaccionar» (repricing con reglas, ganar el catálogo). Es un camino futuro para nosotros (sección 14) y compite con nuestra Publicidad/Precios, no con Mercado.

### Gratis de Mercado Libre
La página pública de **Tendencias** de Mercado Libre muestra las búsquedas en alza por país y categoría (🔎 según UpSeller: hasta 50 palabras, **actualizadas semanalmente**, compuestas por 10 de mayor crecimiento, 20 más populares y 20 más deseadas tras buscar; la herramienta de UpSeller que las muestra agrega un ranking de 3 meses). Es la misma fuente que usa nuestro `/trends`. **Cualquier herramienta que solo repita esto no tiene valor propio.**

### Tabla comparativa

| Capacidad | Nubimetrics (🔎) | Real Trends (🔎) | Crystal Zoom (🔎) | CoreLux hoy | CoreLux objetivo |
|---|---|---|---|---|---|
| Búsquedas en alza por categoría | Sí, con facturación y unidades | No detallado | No | Sí (posición, racha) | Sí, **con tipo de señal y semanas**, más cruce con tu catálogo |
| Ventas / unidades de categorías | Sí | No detallado | No | No | **Índice relativo con el panel** (no ventas absolutas hasta calibrar) |
| Ventas de un competidor | Sí | No detallado | No | No | **Órdenes estimadas** por vendedor (variación de transacciones públicas), con confianza |
| Visitas y conversión de terceros | Sí | No detallado | No | No | **No** (imposible); sí la tuya y la mediana anonimizada de tu rubro |
| Precios de la competencia | Sí | No detallado | Auditoría propia | Solo catálogo y casi vacío | Catálogo **más completo**, con historia y alertas |
| Reputación de vendedores | Sí (ranking) | No detallado | No | Parcial (nivel y medalla) | Completa, con tendencia |
| Margen/ganancia propia cruzada | No (🔎) | Parcial (gestión) | Margen por reglas | **Sí, es nuestro núcleo** | **Oportunidad con tu margen real** |
| Multicuenta | No detallado | Sí | — | Sí (Elite, 2 cuentas) | Tablero de analista |
| IA con herramientas | «Conector MCP» | No detallado | IA de anuncios | Sí (31 herramientas) | Herramientas nuevas de nicho y competidor |

**Posicionamiento:** *«Mercado × tu margen real: las oportunidades que te dejan plata de verdad, no solo las que se venden mucho.»*

---

## 3. Lo que Mercado Libre deja ver y lo que no

### 3.1 Matriz (✅ del sondeo del 2026-10-13, salvo lo marcado)

| Dato | ¿Se puede? | Cómo / límite |
|---|---|---|
| Búsquedas en alza por categoría | ✅ | `/trends/MLA/{cat}`: 9 a 50 palabras, **sin volumen**; la lista **cambia semanalmente** y mezcla tres tipos (ver 3.2) |
| Tamaño de la oferta | ✅ | `/categories/{id}.total_items_in_this_category` (todas las categorías, 1 llamada) |
| Atributos y dominio de cada categoría | ✅ | `/categories/{id}/attributes`, `/catalog_domains/{id}` |
| Interpretar una búsqueda | ✅ | `domain_discovery`: categoría, dominio, atributos (una vez por palabra) |
| Productos de catálogo y sus ofertas | ✅ | `/products/search`, `/products/{id}/items`: precio, precio original, vendedor, FULL, envío gratis, tienda oficial, provincia, garantía, tipo de publicación. **Sin `sold_quantity` ni stock** |
| Comisiones reales por categoría | ✅ | `/sites/MLA/listing_prices` |
| Perfil y reputación de **cualquier** vendedor | ✅ (🔎 campos a verificar) | `/users/{id}`: nivel, medalla, `transactions.total/completed/canceled`, reclamos, demoras, cancelaciones. **Ya leemos `transactions.total` de vendedores ajenos** (`tendencias._perfil_vendedor`) |
| Ventas de los últimos 60 días de un vendedor (`metrics.sales`) | ❓ | Documentado por Mercado Libre en la reputación; **no lo verificamos**: Anexo A, pregunta 1 |
| Reseñas de una publicación ajena | ❓ | `/reviews/item/{id}` dio 404 para ids de catálogo; **no probado con ids de publicaciones ajenas**: Anexo A, pregunta 3 |
| Preguntas públicas de una publicación ajena | ❓ | Anexo A, pregunta 4 |
| `/items/{id}` ajeno, visitas ajenas, `/users/{x}/items/search`, `/sites/MLA/search`, `/highlights` | ⛔ | 403 con token de usuario **y** de aplicación |
| Precio para ganar el puesto de **tus** publicaciones de catálogo | ✅ | `/items/{id}/price_to_win` (solo propias) |
| Visitas, conversión, publicidad de **tus** publicaciones | ✅ | API propia |
| Cuántos vendedores usan el producto | ✅ | de `/products/{id}/items` (hasta ~26 ofertas por producto) |

**Cobertura de catálogo por rubro** (✅ sondeo): celulares y pintura, buena (6 y 5 de 6 productos con ofertas); herramientas, discos y ropa, media (2 de 6); **repuestos, 0 de 6**. En ropa hay apenas 407 productos de catálogo en toda la categoría y **ninguna** de las 275 publicaciones del dueño tiene `catalog_product_id`.

### 3.2 Hallazgo: la lista de búsquedas en alza no es un ranking único

Medido en nuestros 9 días de historia (38 categorías, 342 listas):
- **92 % de los pares de días consecutivos son idénticos** (273 de 296). Cuando cambia, cambia un tercio de las palabras (distancia de Jaccard 0,33). Es una actualización **semanal**: contar «días en la lista» infla las rachas; hay que contar **semanas**.
- En las 30 categorías con 45 o más palabras (240 pares de días), de las posiciones **1–10** sale de la lista el **7 %** por par de días; de las posiciones **11–30** y **31–50**, el **0,2 % y el 0,3 %**, y **casi ninguna cambia de tramo** (0–0,1 %).
- Es lo que se espera si la lista es la concatenación de tres sublistas (🔎 UpSeller: 10 de crecimiento más rápido, 20 populares, 20 más deseadas tras buscar). **Es una hipótesis muy bien apoyada, no una verdad confirmada** (no pudimos leer la documentación oficial: el sitio de desarrolladores bloquea la consulta automática). Confirmarla es la pregunta 2 del Anexo A.

**Qué cambia en el producto:** cada palabra pasa a tener un **tipo de señal** (🔥 *Crece* · ⭐ *Popular* · 🔍 *Deseada tras buscar*), un **nivel de confianza** del tipo y **semanas** en lista. «Subió 3 puestos» deja de mostrarse al cruzar un tramo. Es un dato que ya tenemos y hoy tiramos: la señal de **demanda emergente** (tramo 1–10) es lo más parecido a «volumen» que Mercado Libre regala.

---

## 4. Estrategia: cómo sortear la opacidad con un foso propio

### 4.1 Tres niveles de cobertura (se dicen en pantalla, nunca se esconden)

| Nivel | Cuándo | Qué se puede mostrar |
|---|---|---|
| **A. Con catálogo** | Rubros con buena cobertura de catálogo (electrónica, pintura, herramientas, discos) | Precios, ofertas, vendedores, FULL, concentración, **seguimiento de competidores por producto** |
| **B. Sin catálogo** | Ropa, repuestos, gran parte de los rubros artesanales | Búsquedas en alza, tamaño y variación de la oferta, comisión real, **panel CoreLux** (cuando exista), vendedores **solo si ya se conoce su id** |
| **C. Sin nada** | Categoría sin catálogo, sin panel y sin búsquedas | «Todavía no tenemos datos de este rubro» y se explica qué haría falta. Nada inventado |

### 4.2 Las cinco palancas

1. **Lo público, bien aprovechado.** Cada categoría hoja cuesta 2 llamadas por día (✅ 77–377 llamadas/día hoy con 39 categorías, sin errores). Seguir **todas** las hojas serían decenas de miles de llamadas por día como mucho (❓ **no sabemos cuántas hojas hay**: es la pregunta 12 del Anexo A; con ~5.000, serían ~10.000 por día, ~0,1 por segundo). Mercado Libre no informa límites: se sube de a poco midiendo.
2. **Observación diaria con historia propia.** Cada día sin guardar es un día perdido (✅ la historia empezó el 2026-10-13). Es el único activo que **solo crece con el tiempo** y que nadie puede comprar después.
3. **Órdenes de un vendedor = variación de su contador público.** `transactions.total` de cualquier vendedor sube con cada operación. Dos fotos del mismo vendedor dan **órdenes por período**: no unidades, no pesos, no por producto, incluye todas sus categorías y cancelaciones. Es la única señal de «cuánto vende» que Mercado Libre publica de terceros. **Se activa recién cuando la calibración con nuestras 2 cuentas dé un error aceptable** (ver 5.2).
4. **Panel CoreLux** (decidido: N = 5, función `SECURITY DEFINER`, nunca `conexion_admin` desde la web): la demanda real de los clientes, anonimizada, por **dominio** y semana.
5. **Verdad de referencia propia.** Las 2 cuentas actuales tienen 1 año de órdenes reales: sirven para **medir el error** de cada estimación antes de mostrarla (es lo que ninguna herramienta puede hacer con vendedores ajenos).

### 4.3 El foso: qué datos nadie más tiene (y cómo se construye)

| Capa | Dato | Por qué es único | Estado | Cuándo rinde |
|---|---|---|---|---|
| F1 | **Historia diaria del mercado** (oferta, búsquedas, precios de catálogo) | Lo que Mercado Libre muestra hoy no se puede reconstruir mañana | ✅ desde el 2026-10-13 | Estacionalidad real con 12 meses (primer ciclo completo: Hot Sale y Cyber Monday 2027) |
| F2 | **Ventas reales anonimizadas** de los clientes, por dominio y semana | Ninguna fuente pública las tiene | ❌ falta Términos + opt-in | Con ≥ 5 clientes por dominio |
| F3 | **Precio de venta realizado** (lo que se cobró de verdad, con cuotas y cupones) frente al publicado | Nadie ve el precio real de las operaciones | ⏳ sale del panel | Con F2 |
| F4 | **Costo real de logística** por zona y tipo (FULL, Flex, Correo) | Los vendedores no se comparan entre sí | ✅ lo tenemos por cuenta | Con F2 |
| F5 | **Devoluciones y reclamos por dominio** (riesgo del nicho) | Mercado Libre no lo publica | ✅ por cuenta | Con F2 |
| F6 | **Margen neto real** por modelo (en forma de rango, solo con consentimiento aparte) | Es el dato más sensible y más valioso: «qué nichos dejan plata de verdad» | ⏳ | Con F2 y un segundo opt-in |
| F7 | **Calibración** de cada estimación contra órdenes reales | Permite decir «error medio 18 %» | ✅ 2 cuentas, 1 año | Ya |
| F8 | **Comportamiento de usuarios** (qué nichos guardan o descartan, qué competidores siguen) | Entrena la relevancia | ⏳ | Con uso |

**Volante:** más clientes → panel más grande → más dominios con N ≥ 5 → mejores benchmarks («tu conversión frente a la mediana de tu rubro») → más razones para pagar y para aportar datos. **Hoy el volante está parado en el primer paso.**

### 4.4 Arranque en frío (la parte honesta)

- Hoy: **1 usuario, 2 cuentas, un solo rubro (indumentaria)**. Con N = 5 por categoría, el panel está **vacío**. Cualquier cifra «del panel» que se mostrara hoy sería la de las 2 cuentas del dueño, no del mercado.
- **Anonimato escalonado** (💡): el panel muestra el nivel más fino que junte ≥ 5 aportantes y ≥ 30 órdenes en 4 semanas: **categoría hoja → dominio → rama → raíz**. Con pocos clientes se llega antes a «dominio» (p. ej. `MLA-JACKETS_AND_COATS`) que a una hoja.
- **Programa Pioneros** (💡): invitar a 20–30 vendedores de 3 o 4 rubros distintos (indumentaria, tecnología, hogar, herramientas) con Elite gratis por 3 meses a cambio de activar el panel. Con 5 por rubro, cada rubro «se enciende».
- **Mientras tanto, el módulo no puede depender del panel.** Todo lo que se construya primero tiene que valer con: búsquedas en alza, oferta, catálogo (Nivel A), vendedores observables y **las ventas propias de la cuenta** (que son datos reales de **tu** nicho).
- **Privacidad:** consentimiento explícito (opt-in) en un apartado de Mi cuenta, con vista previa de qué se comparte, y **baja** que deja de aportar desde ese día. Sin nicknames, sin compradores, sin ids de órdenes; solo agregados por dominio y semana. Ley 25.326 de Protección de Datos Personales y términos de la API de Mercado Libre sobre guardar y agregar datos: **a revisar con el abogado antes de la Fase E** (pendiente del dueño, ya anotado). No vamos a leer el contenido de ninguna cuenta con `conexion_admin` desde la web.

### 4.5 Lo que NO vamos a hacer (y lo decimos)

- **Scraping** del sitio de Mercado Libre: viola sus condiciones, expone al bloqueo y es frágil. Hoy Mercado Libre declara que previene la extracción automatizada (🔎 su declaración de privacidad).
- **Prometer ventas absolutas de terceros.** Se muestran índices, rangos y órdenes con la confianza y el origen a la vista.
- **Prometer «ranking SEO» de publicaciones ajenas.** La búsqueda general da 403. Se ofrecen proxies honestos (5.2.4).
- **Rellenar vacíos.** «Sin dato» sigue siendo «sin dato».

---

## 5. Arquitectura funcional

Una sola sección **Mercado** que reemplaza a Mercado + Tendencias + Competencia + Espía. Cuatro pantallas de trabajo (**Radar, Nichos, Competidores, Categorías**) y un centro de **Mis seguimientos** con **Alertas**.

### 5.1 Descubrimiento de nichos («¿qué me conviene vender?»)

**Qué es un nicho** (💡): una combinación de **dominio de Mercado Libre** (`MLA-JACKETS_AND_COATS`) y, opcionalmente, un **atributo clave** (marca, material, capacidad, uso) o un **grupo de búsquedas** relacionadas (agrupadas con `domain_discovery`). Empieza a nivel dominio/categoría hoja (donde hay dato) y se afina cuando el panel lo permite.

**Flujo:**
1. **Entrada guiada** (novato) o **filtros** (analista): rubro, rango de precio, margen mínimo, cómo enviás (FULL/Flex/Correo), capital disponible, dólar sí/no.
2. **Ranking de nichos** con el **Score de Oportunidad** (abajo) y el desglose a la vista.
3. **Ficha de nicho**: semáforo, 5 números, «por qué», «qué necesitás para entrar», **Test de entrada** (simulador de ganancia con tu costo y tus cargos reales, reutilizando la Calculadora) y botón «Seguir este nicho».
4. **Seguir** → entra en Mis seguimientos y genera alertas.

**KPIs de la ficha de nicho (exactos):**

| # | KPI | Fórmula / fuente | Etiqueta | Se muestra si… |
|---|---|---|---|---|
| N1 | **Señal de búsqueda** de cada palabra | tipo (🔥 crece / ⭐ popular / 🔍 deseada) según el tramo de la lista; **semanas en lista**; «nueva» si ≤ 1 semana | Real | la lista tiene ≥ 45 palabras (si no, el tipo es «sin clasificar») |
| N2 | **Momentum de búsquedas** | palabras 🔥 que entraron en las últimas 2 semanas ÷ palabras 🔥 de la lista; y **rotación** = % de la lista que cambió en 4 semanas | Derivado | ≥ 4 semanas de historia |
| N3 | **Oferta** | `total_items_in_this_category` | Real | siempre |
| N4 | **Cambio de oferta** | ΔOF a 7, 30 y 90 días (%) y **frente a su rama** (puntos de diferencia) | Real/Derivado | ≥ 7 días de historia |
| N5 | **Precio de mercado** | mediana P50, P25 y P75 de la muestra de ofertas | Real | ≥ 10 ofertas y ≥ 4 vendedores |
| N6 | **Dispersión de precios** | IQR relativo = (P75 − P25) ÷ P50. **< 0,15** commodity (guerra de precios); **0,15–0,35** normal; **> 0,35** segmentado (hay lugar para diferenciarse) | Derivado | igual que N5 |
| N7 | **Concentración** | % de ofertas del top 3 de vendedores y **HHI** (0–10.000: < 1.500 baja, 1.500–2.500 media, > 2.500 alta) | Derivado | igual que N5 (se dice el tamaño de la muestra) |
| N8 | **Barrera de entrada** | índice 0–100 = promedio de: % FULL (escalado), % tienda oficial, % vendedores con medalla oro/platino, HHI escalado; **y** el precio piso P25 | Derivado | igual que N5 |
| N9 | **Comisión real** | `listing_prices` según categoría y tipo de publicación (clásica/premium) | Real | siempre |
| N10 | **Techo de costo** | **Costo máximo por unidad para ganar tu margen mínimo** = P50 − comisión − envío estimado − P50 × margen mínimo. No necesita que sepas tu costo: «si lo conseguís por menos de $X, vale la pena» | Calculado | hay P50 |
| N11 | **Margen potencial** | con tu costo (de un producto parecido o el que cargues): (P50 − comisión − envío − costo) ÷ P50, en pesos y en %. En USD con tu dólar | Calculado | hay costo |
| N12 | **Demanda del panel** | unidades por semana (media móvil de 4), cambio vs. las 4 anteriores, ticket, **cantidad de vendedores aportantes** | Panel CoreLux | N ≥ 5 y ≥ 30 órdenes en 4 semanas |
| N13 | **Demanda relativa** | participación del nicho en las unidades de su rama (panel) ÷ participación del nicho en la oferta de su rama: **> 1,2** hay más demanda que oferta; **< 0,8** sobreoferta | Panel + Real | panel disponible |
| N14 | **Estacionalidad** | índice mensual = unidades del mes ÷ promedio de 12 meses (panel o historia propia) y **próximas fechas comerciales** del calendario (Hot Sale, Cyber Monday, Día del Padre…) | Panel/Calendario | 12 meses de historia; antes solo el calendario |
| N15 | **Fase del ciclo** | regla: *emergente* (demanda ↑ y oferta estable), *crecimiento* (demanda ↑ y oferta ↑), *madura* (ambas estables), *saturación* (oferta ↑ y demanda estable), *declive* (demanda ↓) | Derivado | N2 o N12 y N4 |
| N16 | **Fit contigo** | 0–100: cercanía a tus ventas (mismo dominio 100, misma rama 60, otra raíz 20), tu margen mínimo contra N11, tu logística contra N8 | Calculado | tenés ventas |
| N17 | **Riesgo** | volatilidad (variación de la mediana en 30 días), peso de reclamos/devoluciones del dominio (panel), dependencia del dólar (costo en USD) | Derivado | según dato |

**Score de Oportunidad (0–100) — fórmula visible, no una caja negra:**

```
Score = Σ (peso_i × puntaje_i) ÷ Σ (pesos disponibles)      cada puntaje_i va de 0 a 100
  Demanda creciente   30   panel: percentil del cambio de demanda entre nichos hermanos; sin panel: momentum de búsquedas (N2)
  Margen potencial    25   0 si ≤ tu margen mínimo; 100 si ≥ 40 %; lineal en el medio (usa el techo de costo si no hay costo)
  Baja saturación     20   100 − percentil de (oferta ÷ demanda relativa); sin panel: 100 − percentil de N4 y N7
  Accesibilidad       15   100 − barrera de entrada (N8), ajustada a tu logística
  Estacionalidad       10   +100 si hay una fecha comercial del dominio en los próximos 60 días; 50 si no hay dato
Confianza = suma de los pesos disponibles ÷ 100:  ●●● ≥ 80 · ●●○ 50–79 · ●○○ < 50
```
Si faltan componentes, el score **se recalcula con los que hay y baja la confianza**; nunca rellena con ceros. La pantalla muestra «Oportunidad 72 · confianza ●●○ · falta: demanda del panel».

**Descubrimiento de nichos para un rubro sin catálogo (Nivel B):** el score usa búsquedas, oferta, comisión y techo de costo; **no usa precios del mercado**. Se avisa: «Para ropa no vemos los precios de otros vendedores. Estos nichos se ordenan por cuánto se busca y cuánta oferta hay.»

### 5.2 Competidores y publicaciones («¿qué hace mi competencia?»)

**Entidades:** el **Producto de catálogo** (ya existe), el **Vendedor** (nuevo: `seller_id`) y **Mi publicación** (propia). Se sigue a un producto o a un vendedor; el sistema **descubre los demás** solo.

**5.2.1 Cómo se arma la lista sin que la persona pegue links** (💡, hoy hay 0 seguimientos porque cargar es trabajo):
- **Mis rivales directos automáticos**: para cada publicación **de catálogo** tuya, los vendedores que comparten el producto (de `/products/{id}/items`).
- **Rivales de mi rubro**: para cada dominio donde vendés, los vendedores más frecuentes en las ofertas de catálogo de ese dominio.
- **Alta manual** con link o id de producto de catálogo, o id de vendedor. (Un **link de publicación común no alcanza**: `/items/{id}` ajeno es 403 y no se puede ni saber quién es el vendedor. Se explica.)
- El **Radar de competencia** sugiere «este vendedor aparece en 4 de tus productos y bajó precios 3 veces este mes: ¿lo seguís?».

**5.2.2 KPIs de producto y publicación:**

| # | KPI | Fórmula / fuente | Etiqueta |
|---|---|---|---|
| C1 | **Índice de precio relativo (IPR)** | tu precio ÷ mediana de las ofertas activas del mismo producto (mismo estado de producto). **< 0,95** más barato · **0,95–1,05** alineado · **> 1,05** más caro | Real/Calculado |
| C2 | **Posición de precio** | tu puesto entre las n ofertas y cuánto te falta para ser la más barata | Real |
| C3 | **Distancia al puesto principal** | `price_to_win` de tus publicaciones de catálogo (precio exacto para ganar y si te conviene según tu margen) | Real (propio; ❓ construido contra la documentación: la cuenta de prueba no tiene catálogo) |
| C4 | **Movimiento de precio rival** | cambio a 7 y 30 días (%), cantidad de cambios en 30 días, fecha de la última baja | Real (historia propia) |
| C5 | **Guerra de precios** | alerta cuando **≥ 2 vendedores** del mismo producto hicieron **≥ 3 bajas de ≥ 2 %** en 14 días | Derivado |
| C6 | **Logística del producto** | % de ofertas FULL, % envío gratis, y tu tipo de envío frente a la mayoría («el 70 % de tus rivales está en FULL y vos no») | Real |
| C7 | **Entradas y salidas** | vendedores nuevos en tus productos en 7 días; ofertas que desaparecen (posible quiebre de stock) y vuelven | Derivado |
| C8 | **Mi posición de visitas** | `visit_share` y estado de `price_to_win` de tus publicaciones de catálogo (máx./medio/mín.) | Real (propio; ❓ igual que C3) |
| C9 | **Posición en la búsqueda de catálogo** por palabra | lugar de un producto de catálogo en `/products/search?q=` (**aproximado**: es la búsqueda de catálogo, no la del sitio) | Aproximado |

**5.2.3 KPIs de vendedor (competidor):**

| # | KPI | Fórmula / fuente | Etiqueta |
|---|---|---|---|
| V1 | **Perfil** | nivel, medalla, antigüedad, tienda oficial | Real |
| V2 | **Salud del vendedor** | reclamos, demoras en despacho y cancelaciones (% del período) de su reputación pública y su tendencia a 30 días | Real |
| V3 | **Órdenes estimadas por semana** | `transactions.total(hoy) − transactions.total(hace 7 días)` (suma completadas y canceladas, todas sus categorías); se muestra **como rango** con el error medido en la calibración | Estimado |
| V4 | **Tamaño relativo** | sus órdenes de 30 días ÷ la mediana de los vendedores observados en el mismo dominio | Estimado |
| V5 | **Cuota de órdenes observadas** | sus órdenes ÷ suma de las de los vendedores observados en el dominio (**solo entre los que observamos**; se dice «de los 14 vendedores que seguimos») | Estimado |
| V6 | **Solapamiento contigo** | en cuántos de tus productos compite y qué % de tu catálogo comparte | Real |
| V7 | **Ventas de 60 días** (`metrics.sales`) | si el sondeo confirma que existe y es público: lectura directa, sin estimar | ❓ Real (a verificar) |

**Calibración obligatoria antes de mostrar V3–V5** (💡): guardar cada día `transactions.total` de **nuestras 2 cuentas** (que además conocemos por `ventas`) y medir el error de la estimación contra las órdenes reales de 8 semanas. **Criterio de salida:** error absoluto medio **≤ 20 %** por semana y **sin sesgo sistemático** (el contador puede contar operaciones con retraso o incluir canceladas). Si no se cumple, **V3 no se muestra** y se queda V1–V2.

**5.2.4 «Ranking SEO»: qué prometemos y qué no**
- ⛔ **No se puede** medir la posición de una publicación en la búsqueda del sitio (la búsqueda general es 403).
- ✅ Lo que sí: **(a)** las palabras en alza de tu categoría y cuáles **ya están en tus títulos** (hoy existe: Score de SEO) con **la señal de tipo** (🔥/⭐/🔍) para priorizar; **(b)** la **calidad** de tu publicación según Mercado Libre (`performance`) y la acción concreta para subirla; **(c)** tu **posición de visitas** en catálogo (C8); **(d)** la **posición aproximada en la búsqueda de catálogo** (C9). Cada uno con su etiqueta. Se llama **«Visibilidad»**, no «ranking SEO».

**5.2.5 «Estimación de ventas»: qué se puede decir en cada nivel**

| Qué | Cómo | Etiqueta |
|---|---|---|
| Ventas de **tu** publicación | API propia | Real |
| Órdenes de **un competidor** | V3 (con calibración) | Estimado |
| Tendencia de demanda de un **dominio** | panel (N ≥ 5) | Panel CoreLux |
| Unidades **absolutas** de un dominio | `unidades_panel ÷ cobertura`, donde **cobertura = suma de las órdenes de nuestros clientes ÷ suma de las órdenes de todos los vendedores observados en el dominio** (ambas por la variación de `transactions.total`). Se muestra como **rango** y solo con ≥ 30 vendedores observados y la cobertura medida | Estimado (baja confianza) |
| Unidades de un competidor puntual | **no se estiman** | — |
| Ventas por reseñas | solo si el sondeo confirma reseñas públicas por publicación: reseñas nuevas ÷ tasa de reseña (3–8 %, a medir con nuestras cuentas) | ❓ Estimado |

### 5.3 Mapa de categorías («¿hacia dónde va mi rubro?»)

**Qué es:** el árbol de Mercado Libre pintado por **momentum**. Cada nodo (raíz → hoja) con tamaño = oferta, color = tendencia, y un panel lateral al tocarlo.

**KPIs por categoría:**

| # | KPI | Fórmula / fuente | Etiqueta |
|---|---|---|---|
| M1 | **Expansión de la oferta** | ΔOF 7/30/90 d (%) y frente a su rama | Real |
| M2 | **Demanda** | panel: índice de unidades (base 100 = hace 12 semanas) y cambio de 4 semanas; sin panel: momentum de búsquedas (N2) | Panel / Derivado |
| M3 | **Relación demanda ÷ oferta** | N13 por categoría | Panel + Real |
| M4 | **Precio** | cambio de la mediana (30 y 90 d), **en pesos, en dólares (MEP) y deflactado por IPC** | Real + externa |
| M5 | **Logística** | cambio del % FULL y envío gratis (muestra) | Real |
| M6 | **Concentración** | cambio del HHI (¿entran jugadores grandes?) | Derivado |
| M7 | **Entrantes** | vendedores nuevos en la muestra por semana | Derivado |
| M8 | **Estacionalidad** | curva de 12 meses | Panel |
| M9 | **Fase del ciclo** | regla N15 | Derivado |
| M10 | **Temperatura** | índice 0–100 combinando M2, M1 y M9; semáforo: 🟢 calentándose · 🟡 estable · 🔴 enfriándose | Derivado |
| M11 | **Mapa geográfico** | reparto de ofertas por provincia (`seller_address`) y, con panel, de la demanda por provincia | Real / Panel |
| M12 | **Cobertura del dato** | qué nivel (A/B/C) tiene esa categoría y cuántos días de historia | Real |

**Vistas:** (1) **Treemap** por raíz con filtro por temperatura; (2) **Tabla de categorías** ordenable (la actual «Comparar», mejorada); (3) **Detalle** con las series y la lectura en lenguaje simple; (4) **Comparador** de hasta 4 categorías; (5) **Calendario** estacional.

### 5.4 Panel CoreLux: benchmarks entre pares (el diferencial de largo plazo)

Con N ≥ 5 por dominio, el panel permite cosas que ningún competidor ofrece: **«tu conversión frente a la mediana de tu rubro»**, ticket, % FULL, % envío gratis, tasa de devoluciones, de reclamos y de cancelaciones, tiempo de despacho y **precio realizado frente a publicado**. Todas como **mediana y rango intercuartílico**, nunca el dato de uno.
⚠️ Esto **contradice una regla actual del asistente** («no comparar con otros vendedores: Mercado Libre no da ese dato»). Cuando el panel exista, la regla cambia a «solo con el panel y diciendo de cuántos vendedores sale». Es una **decisión que tiene que aprobar el dueño** (sección 15).

### 5.5 Mis seguimientos y Alertas

**Se sigue:** un nicho, una categoría, un producto de catálogo, un vendedor, una palabra. Un tablero único con sparklines y lo que cambió desde la última visita.

| Alerta | Condición | Canal inicial |
|---|---|---|
| Un rival bajó el precio | −3 % o más en un producto que seguís o compartís | Campana + mail |
| Guerra de precios | C5 | Campana |
| Estás más caro que el mercado | IPR > 1,05 por 3 días | Resumen semanal |
| Nicho que se calienta | M10 pasa de 🟡 a 🟢 o N2 sube de umbral | Resumen semanal |
| Palabra nueva en 🔥 | una palabra entra en el tramo 1–10 de tu categoría y no está en tus títulos | Campana |
| Saturación | N4 sube más de 15 % en 30 días con demanda estable | Resumen semanal |
| Rival sin stock | su oferta desaparece de tu producto de catálogo | Campana |
| Fecha comercial cerca | faltan 30 / 14 / 7 días de Hot Sale, Cyber Monday… y tu nicho tiene pico | Resumen semanal |

**Reglas:** tope de 5 alertas por día por cuenta, agrupadas; cada una dice **qué pasó, por qué importa y qué hacer** (con botón a la pantalla donde se hace). Más adelante, WhatsApp (Epic aparte) y mail (cuando se encienda).

---

## 6. Diseño de experiencia (UX)

### 6.1 Personas

| | **Lucía, la que empieza** | **Diego, el vendedor en crecimiento** | **Marcos, el analista de cuentas** |
|---|---|---|---|
| Quién es | Vende poco o nada, quiere saber **qué** vender | Vende (400 ventas/mes), quiere **no perder terreno** | Gestiona 2 o más cuentas (agencia o consultor, plan Elite) |
| Pregunta | «¿En qué me meto?» | «¿Cómo voy frente al mercado y qué hago esta semana?» | «¿Qué cuenta/nicho necesita atención y puedo llevármelo a Excel?» |
| Tolera | 3 números, un semáforo, una acción | 10 números, series, tendencias | Todo: tablas, filtros, rangos, exportación |
| Entrada | **Modo Guía** | **Modo Seguimiento** | **Modo Analista** |

El modo se **recuerda por persona** y se cambia con un selector arriba a la derecha; **no son tres productos**, son tres niveles de detalle sobre los mismos datos (**divulgación progresiva**).

### 6.2 Mapa de pantallas

```
MERCADO
 ├─ Radar            (inicio) lo que cambió esta semana en TU rubro + 3 acciones
 ├─ Nichos           descubrir y comparar (Guía: 3 preguntas · Analista: filtros)
 │    └─ Ficha de nicho   semáforo, KPIs, «por qué», Test de entrada, Seguir
 ├─ Competidores     productos y vendedores que seguís + descubiertos
 │    ├─ Ficha de producto   precios, ofertas, historia, alertas
 │    └─ Ficha de vendedor   reputación, órdenes estimadas, solapamiento
 ├─ Categorías       treemap + tabla + comparador + calendario
 └─ Mis seguimientos tablero y alertas (con «qué cambió desde que viniste»)
```
Cada pantalla respeta las reglas del sistema (CLAUDE.md): **cómo voy → qué hago → números → detalle plegado**, un botón principal, color solo en lo que hay que mirar, glosario de la plata, **toda cifra con su origen** (Real · Calculado · Panel · Estimado) y su **muestra** («de 14 ofertas»).

### 6.3 Bocetos

**Radar (Modo Seguimiento)**
```
┌ Mercado · Radar ───────────────────────────────  [Guía | Seguimiento | Analista] ┐
│ Tu rubro: Camperas y abrigos · datos de 38 días            Cobertura: ●●○ catálogo │
│ ┌ Esta semana en tu rubro ─────────────────────────────────────────────────────┐ │
│ │ 🔥 3 búsquedas nuevas creciendo: «campera puffer mujer»  «parka corta»  «…»      │ │
│ │ 🟡 Oferta +4 % en 30 días (tu rama: +2 %)    🟢 Demanda +9 % (panel, 7 vendedores) │ │
│ └──────────────────────────────────────────────────────────────────────────────┘ │
│ ¿Qué hago esta semana?                                                             │
│  1 ▸ «parka corta» no está en ninguno de tus títulos      [Optimizar título]        │
│  2 ▸ Tu «Campera Jean Negra» está +8 % arriba del mercado  [Ver precios]            │
│  3 ▸ Hot Sale en 41 días: tu rubro pica ×1,6               [Preparar stock]         │
│ Mis seguimientos (5)   ▁▂▃▅▆  Nichos 2 · Rivales 3 · Palabras 4        [Ver todo]   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Nichos (Modo Guía)**
```
 «¿Qué vendo?»   1) ¿Qué precio querés vender?  [ $20.000 – $80.000 ]
                 2) ¿Cuánto podés invertir?     [ hasta $500.000 ]
                 3) ¿Cómo enviás?               [ Correo ▾ ]            [Ver 5 ideas]
 ┌ Parkas cortas de mujer ───────────── Oportunidad 78 ●●○ ┐   ┌ Fundas para notebook ── 71 ●●● ┐
 │ 🟢 Se busca cada vez más · 🟡 Competencia media          │   │ …                              │
 │ Si lo conseguís por menos de $24.000, ganás tu 20 %      │   │                                │
 │ Necesitás: stock de ~15 unidades (capital $360.000)      │   │                                │
 │ [Simular mi ganancia]  [Seguir]            ver el cálculo ▸ │ └────────────────────────────────┘
 └──────────────────────────────────────────────────────────┘
```

**Ficha de producto (Modo Analista)**
```
 Producto: Apple iPhone 15 128 GB · 14 ofertas · muestra del 21/10
 Precio: P25 $1.480.000 · mediana $1.560.000 · P75 $1.690.000   IPR tuyo 1,03 (alineado)
 [ serie de precio 90 d con banda P25–P75 y marcas de cambios ]        [Exportar CSV]
 Ofertas (ordenable)  Vendedor · nivel · precio · FULL · envío gratis · Δ7d · órdenes/sem (estim.) ●●○
```

### 6.4 Reglas de diseño específicas

- **Etiqueta de origen y de confianza** en cada número (`Real` verde-azulado, `Panel` violeta, `Calculado` gris, `Estimado` naranja con rango y puntos ●●○).
- **Estados que ya no engañan:** «Juntando datos: faltan 12 días para mostrar la tendencia» (con barra), «Sin catálogo en este rubro: se ordena por búsquedas y oferta» (explica el Nivel B), «Con 3 vendedores no mostramos este dato (mínimo 5)».
- **Novato:** máximo 3 números por tarjeta, nunca una sigla sin explicar (HHI → «cuánto se reparten el mercado los 3 más grandes»), siempre «qué hago».
- **Analista:** todas las tablas **ordenables** (`tablas.js`), filtros que se guardan, **exportar a CSV/Excel** respetando el formato argentino, vista de **rangos** (no un número solo) y **comparar hasta 4**.
- **Celular primero:** tarjetas en una columna, sparkline en cada una, acciones al pulgar (barra inferior), tablas de analista como tarjetas con «ver más».
- **Accesibilidad:** semáforo siempre con texto y forma además del color; gráficos con alternativa en texto; objetivos táctiles de 44 px.
- **Lenguaje:** voseo, frases con el dato adentro, sin signos de exclamación, sin «oportunidad única». Las estimaciones empiezan con «Estimamos…».

---

## 7. Catálogo maestro de KPIs

Resumen para decidir qué se construye en cada fase (las fórmulas están en 5.1–5.3).

| Fase | KPIs |
|---|---|
| **B (Radar + Nichos v1)** | N1, N2, N3, N4, N9, N10, N16 (+ N5–N8, N11 donde hay catálogo), Score de Oportunidad con confianza |
| **C (Competidores)** | C1–C8, V1, V2, V6; luego V3–V5 tras la calibración |
| **D (Categorías)** | M1, M4–M7, M9–M12 (M2, M3, M8 con panel) |
| **E (Panel)** | N12, N13, N14, N17, M2, M3, M8, benchmarks 5.4, unidades absolutas (5.2.5) |

**Reglas de cálculo comunes:** mínimo de muestra explícito por KPI (se dice cuando no se alcanza); **semanas**, no días, para toda señal que derive de `/trends`; medianas y percentiles en vez de promedios; precios con su fecha de muestra; el costo del usuario en pesos o en dólares con su cotización; **ningún KPI sin origen y sin muestra**.

---

## 8. Datos y operación (alto nivel, sin código)

**Reutiliza lo ya construido:** las tablas globales `mercado_*` (solo lectura para la app, las escribe un único trabajo con la conexión de administración), el relevador diario, el panel de salud del relevamiento (`/admin/salud`) y `cache_db`.

**Tablas nuevas (💡, nombres tentativos):**

| Tabla | Para qué | Cadencia / retención |
|---|---|---|
| `mercado_tendencias_semanales` | versión de la lista **por semana** con el tramo de cada palabra (🔥/⭐/🔍) | una por cambio detectado; 2 años |
| `mercado_ofertas_semana` | foto semanal de las ofertas de cada producto de catálogo seguido (vendedor, precio, FULL, envío gratis, descuento) | semanal; 90 días detalle, luego resumen |
| `vendedores` + `vendedores_diario` | `seller_id`, apodo, y una foto diaria de reputación y `transactions.*` | diaria; 1 año |
| `nichos` + `nichos_metricas_semanales` | definición de cada nicho y sus KPIs calculados por semana (alimenta el Score y el histórico) | semanal; 2 años |
| `panel_demanda_semanal` | agregados anonimizados por dominio (unidades, órdenes, vendedores aportantes, ticket, precio realizado, logística) | semanal; función `SECURITY DEFINER`; solo con N ≥ 5 |
| `seguimientos_usuario` | qué sigue cada cuenta (nicho, categoría, producto, vendedor, palabra), con `cuenta_id` y RLS por cuenta activa | — |
| `alertas_mercado` | reglas y eventos, con tope diario | 90 días |
| `calibracion_estimaciones` | estimado vs. real de nuestras cuentas, para medir el error | semanal; permanente |

**Presupuesto de llamadas a Mercado Libre (estimado, a medir):**
- Hoy: 39 categorías, 77–377 por día, 0 errores.
- Seguir **todas las categorías hoja** (❓ cantidad sin verificar; **si fueran ~5.000**): 2 llamadas diarias ≈ 10.000/día (~0,12 por segundo).
- Muestra de catálogo semanal para ~1.000 productos: ~1.000 llamadas por semana (1 por producto, hasta 26 ofertas).
- Vendedores: 1 llamada diaria por vendedor seguido; 5.000 vendedores = 5.000/día.
- **Total objetivo:** del orden de 15.000–20.000 por día (depende de cuántas hojas haya); **sin cabeceras de límite**, se sube de a poco midiendo errores y tiempos (el panel de `/admin/salud` ya enciende rojo si falla un tipo de relevamiento).

**Calidad del dato:** cada serie guarda `tomada_en` y si el día se midió o no (**`NULL` = no se midió, nunca cero**); un chequeo diario de huecos; la muestra de catálogo se prioriza por **dominio** (no solo por hoja: hoy 33 de 39 categorías seguidas nunca se muestrearon porque son raíces) y se reintenta lo que dio 0 ofertas con la búsqueda del dominio completo.

**Privacidad y seguridad:** el panel solo sale por función `SECURITY DEFINER` con mínimo N = 5 y mínimo de órdenes, con **anonimato escalonado** (hoja → dominio → rama → raíz) y sin dato individual; opt-in explícito y baja inmediata; ninguna lectura de cuentas ajenas desde la web; todo lo nuevo auditado (`auditoria`) cuando cambia datos.

---

## 9. Integración con el resto de CoreLux

**Principio: cada insight termina en una acción dentro de la app.**

| Desde Mercado | Hacia |
|---|---|
| «Estás +8 % arriba del mercado» | **Precios** (precio mínimo, recomendado, cambiar con vista previa) |
| «Nicho nuevo: techo de costo $24.000» | **Calculadora** (Test de entrada con comisión, envío y devoluciones reales) y **Costos** (cargar el costo) |
| «Palabra 🔥 que no está en tus títulos» | **Calidad / Score de SEO** (optimizar título) |
| «Tu nicho se calienta y te queda stock para 6 días» | **Stock** (reposición) |
| «Fecha comercial en 30 días» | **Promociones** (armar descuento) y **Publicidad** |
| «El rival tiene FULL y vos no» | **Comparador de logística** |
| Preguntas en lenguaje natural | **Asistente de IA**: herramientas nuevas `nicho`, `competidor`, `categoria_mapa`, `alertas` (solo lectura, mismas 3 capas de alcance) |
| Resumen del lunes | **Campana** (hoy) y mail/WhatsApp (cuando existan) |

**Informe de nicho (PDF/Excel)** para socios, bancos o proveedores, con fuentes y confianza a la vista.

---

## 10. Planes y modelo de negocio (hipótesis, a validar)

| | **Base** | **Elite** | **Agencia** (💡 nuevo) |
|---|---|---|---|
| Radar y Mapa de categorías | Sí | Sí | Sí |
| Nichos | Ranking + 3 nichos seguidos | Ilimitados + Test de entrada completo | Ilimitados |
| Competidores | 5 productos / 3 vendedores | 30 / 20, descubrimiento automático | 100+ |
| Alertas | Campana + resumen semanal | + tiempo real (WhatsApp cuando exista) | + por cliente |
| Panel / benchmarks | Mediana de tu rubro | + rangos y por dominio | + comparación entre tus clientes |
| Analista | — | Exportar CSV/Excel | Tablero multi-cuenta, informes automáticos, API/Sheets |

Notas: hoy Elite admite **2 cuentas** (`MAX_CUENTAS_ELITE`); el perfil Marcos en serio necesita **más** (agencias con 5–20 clientes): es un plan nuevo, decisión comercial del dueño. Aportar al panel se premia con más acceso (**«dar para recibir»**). El módulo es la mejor razón para pasar de Base a Elite.

---

## 11. Roadmap por fases (con criterios de salida)

Esfuerzo relativo: **S** unas horas · **M** 1–2 días · **L** una semana o más. El ritmo real lo define cada tanda con el dueño.

| Fase | Qué | Esfuerzo | Criterio de salida |
|---|---|---|---|
| **0b · Verificar** | Sondeo de solo lectura (Anexo A): 12 preguntas, ~100 llamadas, en Fly con el token de aplicación | S | Cada pregunta con respuesta ✅/⛔ anotada en `SONDEO_FASE0.md` |
| **A · Cimientos de datos** | (1) semanas y tramos de `/trends`; (2) muestreo de catálogo por **dominio** (arreglar los 33 sin muestra y los 0 ofertas); (3) foto diaria de reputación de vendedores y de **nuestras 2 cuentas**; (4) fotos semanales de ofertas; (5) medir presupuesto real de llamadas | M–L | Todas las categorías seguidas con muestra (o marcadas Nivel B); calibración corriendo; 0 errores sostenidos |
| **B · Radar + Nichos v1** | Pantallas **Radar** y **Nichos** (Guía y Analista), Score de Oportunidad con confianza, Test de entrada, Seguir | L | Un vendedor nuevo llega a una ficha de nicho y simula su margen en < 60 s; el score nunca muestra un componente sin dato |
| **C · Competidores v2** | Reemplaza a «Competencia» y al Espía: descubrimiento automático, fichas de producto y vendedor, IPR, movimientos, alertas | L | ≥ 80 % de las cuentas con catálogo ven rivales sin cargar nada; calibración de V3 con error ≤ 20 % antes de mostrarlo |
| **D · Mapa de categorías** | Treemap, tabla, comparador, calendario estacional, temperatura | M–L | Toda categoría seguida con M1–M12 (o su «sin dato» explicado) |
| **E · Panel CoreLux** | Términos y Privacidad, opt-in, `panel_demanda_semanal`, benchmarks, demanda y estacionalidad, cambio de la regla del asistente | L | ≥ 5 aportantes en ≥ 3 dominios; revisión legal hecha; ningún dato bajo N |
| **F · Analista** | Tablero multi-cuenta, exportación, informes semanales, herramientas de IA nuevas, (💡 plan Agencia) | M–L | Un analista compara 2 cuentas y baja el informe sin ayuda |

**Qué se retira o se reemplaza:** `Tendencias` (radar vivo, explorador en vivo, cachés en memoria por proceso: se absorben en Radar/Nichos con datos guardados); `Competencia/Espía` (0 seguimientos cargados); el seguimiento **por cuenta** de `tendencias_snapshots` (a las tablas globales, ya previsto); `explorar_mercado` en vivo (25–35 llamadas por consulta: pasa a leer lo guardado y a pedir a Mercado Libre solo lo que falte, con caché compartida).
**Qué se conserva:** Score de SEO, calendario comercial, catálogo para ganar (`price_to_win`), `mercado.py` como base de Categorías.

---

## 12. Riesgos y mitigaciones

| Riesgo | Probabilidad / impacto | Mitigación |
|---|---|---|
| Mercado Libre cierra otro endpoint (ya cerró tres) | Media / Alto | Cada KPI degrada con cartel; el relevador ya avisa en `/admin/salud`; **no depender de uno solo** |
| El panel nunca llega a N = 5 | Media / Alto | Anonimato escalonado, Programa Pioneros, valor del módulo **sin** panel desde la Fase B |
| Estimación de órdenes (V3) falla la calibración | Media / Medio | Criterio de salida explícito; si no pasa, se queda V1–V2 y se dice por qué |
| Sesgo del panel (pocos rubros, vendedores chicos) | Alta / Medio | Mostrar «de N vendedores», rangos, y nunca extrapolar a «el mercado» sin cobertura medida |
| Expectativas puestas por los rivales («ventas exactas») | Alta / Medio | Posicionar con honestidad: «sabemos lo que dejás de ganar, no lo que ganan otros» |
| Legal: términos de la API de Mercado Libre y Ley 25.326 | Media / Alto | Revisión legal antes de la Fase E; opt-in; sin datos personales; sin scraping |
| Historia corta frente a competidores (2016 contra 2026) | Cierta / Medio | No competir en historia: competir en **margen real + datos propios**; acumular desde hoy |
| Costo y límites de llamadas | Baja / Medio | Subir de a poco, medir, caché compartida, prioridad por interés |
| Complejidad de la pantalla | Media / Medio | Tres modos, divulgación progresiva, un botón principal, prueba de 5 segundos con 5 personas |

---

## 13. Cómo sabremos que funciona (métricas del producto)

| Métrica | Meta inicial |
|---|---|
| **Activación**: cuentas que guardan ≥ 1 nicho o competidor en sus primeros 7 días | ≥ 40 % |
| **Uso semanal** del módulo entre cuentas activas | ≥ 50 % |
| **Decisión**: clics de «qué hago» que terminan en un cambio (precio, título, stock, promoción) | ≥ 20 % de las alertas abiertas |
| **Tiempo hasta el primer insight** de un novato | < 60 s |
| **Exactitud** de V3 contra órdenes reales | error medio ≤ 20 % |
| **Cobertura de catálogo** de las categorías seguidas con ≥ 5 ofertas en la muestra | ≥ 80 % en Nivel A |
| **Frescura**: relevamiento diario completo antes de las 06:00 | 99 % de los días |
| **Confianza del usuario**: «¿te sirvió?» 👍 en cada pantalla | ≥ 80 % |
| **Retención**: efecto del módulo en la baja de suscripciones | a medir contra el mes previo |
| **Panel**: dominios con N ≥ 5 | 3 al cierre de la Fase E |

---

## 14. Más ideas (bienvenidas y propuestas)

1. **Test de entrada al nicho** (simulador): con tu costo, tu comisión real, tu logística y tu dólar, cuánto ganarías con 20, 50 o 100 unidades, y con qué margen si el precio baja 10 %. Reutiliza la Calculadora. *Es lo que más separa a CoreLux de una herramienta de tendencias.*
2. **«Tu cuota de catálogo»**: en cuántos productos de catálogo estás y en cuántos tenés el puesto principal.
3. **Benchmark entre pares** (sección 5.4): conversión, devoluciones, tiempo de despacho y precio realizado frente a la mediana de tu rubro. Es el producto que **solo** nuestro panel puede dar.
4. **Detector de guerra de precios** y recomendación: «no bajes: tu margen quedaría en 4 %; ofrecé envío rápido».
5. **Rival fantasma**: grupos de publicaciones del mismo vendedor que se disfrazan de varios (mismos productos, mismas fechas de cambio de precio).
6. **Calendario de oportunidades personalizado**: Hot Sale, Cyber Monday, Día del Padre con **tu** curva y la del panel («el año pasado vendiste ×2,4 la semana previa»).
7. **Radar de lanzamientos de catálogo**: productos nuevos del dominio con pocas ofertas.
8. **Alerta de quiebre del rival**: su oferta desaparece de tu producto = ventana para subir precio o empujar publicidad.
9. **Sensibilidad al dólar**: para quien importa, cuánto pierde de margen por cada +5 % del dólar y qué nichos son más inmunes.
10. **Mapa de calor por provincia**: dónde se vende y dónde no hay oferta local (oportunidad Flex o de envío más rápido).
11. **«Compra inteligente»** para importadores: costo en dólares contra la tendencia del precio y del dólar: ¿comprar ahora o esperar?
12. **Índice CoreLux mensual** (contenido público): «qué rubros crecieron este mes» con datos del panel. Marketing que además enseña el valor del panel.
13. **Briefing del lunes** por mail/WhatsApp: tres líneas de lo que cambió en tu rubro y una acción.
14. **Sustitutos**: nichos vecinos del mismo dominio que están creciendo más que el tuyo.
15. **Del insight a la acción automática** (inspirado en Crystal Zoom): reglas de reprecio con tope de margen (con confirmación y vista previa; **nunca** automático sin permiso explícito).
16. **Conector para asistentes de IA** (Nubimetrics ofrece un «Conector MCP»): exponer las mismas herramientas de solo lectura de nuestro asistente a otros clientes de IA del analista.
17. **Etiqueta de calidad de dato** por categoría (A/B/C) visible en todo el producto, como sello de honestidad.
18. **Lista de deseos de proveedor**: guardar nichos y «techo de costo» para llevarlos a un proveedor («necesito esto por menos de $X»).
19. **Ranking comunitario anónimo**: «los nichos más guardados esta semana por vendedores como vos».
20. **Más adelante, otros mercados** (Tiendanube, Shopify, redes): el relevador y el modelo de nicho/dominio son genéricos; se evalúa después de consolidar Mercado Libre.

---

## 15. Decisiones que necesito de vos

1. **Sondeo 0b** (solo lectura, ~100 llamadas, en una máquina de Fly con el token de aplicación, sin tocar datos): ¿lo autorizás? Es el primer paso y define qué prometemos.
2. **Alcance del relevador**: ¿seguimos **todas las categorías hoja** (decenas de miles de llamadas por día como máximo, a medir en el sondeo) o solo las de tus clientes y las raíces? (Recomiendo todas, subiendo de a poco.)
3. **Panel**: ¿aprobás el **Programa Pioneros** (20–30 vendedores con Elite gratis por 3 meses a cambio de aportar) y empezás con el abogado la actualización de Términos/Privacidad y la revisión de los términos de la API?
4. **Regla del asistente**: cuando exista el panel, ¿permitimos comparar con otros vendedores **solo con datos del panel y diciendo de cuántos**?
5. **Retirar** Tendencias y Competencia/Espía cuando Radar/Nichos y Competidores cubran lo que hacen (sin avisar a nadie: hoy no hay usuarios que las usen más que vos).
6. **Planes**: ¿te interesa un plan **Agencia** (varias cuentas) o por ahora el analista es el Elite de 2 cuentas?
7. **Nombre y lugar en el menú**: ¿«Mercado» como sección propia (hoy está dentro de «Crecimiento»)? ¿Los tres modos se llaman Guía, Seguimiento y Analista?
8. **Honestidad como producto**: ¿confirmás que **no** mostramos estimaciones de ventas de terceros hasta pasar la calibración, aunque los rivales sí las muestren?

---

## Anexo A. Sondeo 0b: 12 preguntas por verificar (solo lectura)

Mismo método que la Fase 0 (`sondeo_meli.py`, token de aplicación, sin tokens ni datos personales en pantalla). Cada respuesta se anota en `SONDEO_FASE0.md`.

| # | Pregunta | Cómo se prueba | Qué cambia según la respuesta |
|---|---|---|---|
| 1 | ¿`/users/{id}` de **otro** vendedor trae `seller_reputation.metrics.sales` (ventas de 60 días) y `transactions.total/completed/canceled`? | Leer 20 vendedores de ofertas de catálogo | Si sí: V7 pasa a **Real** y V3 se vuelve secundario |
| 2 | ¿La lista de `/trends/MLA/{cat}` es 10 + 20 + 20 (crece / popular / deseada)? | Comparar con la página oficial de Tendencias y con 3 semanas de historia propia | Confirma o descarta el «tipo de señal» (N1) |
| 3 | ¿`/reviews/item/{item_id}` funciona con ids de **publicaciones ajenas** (no de catálogo)? | Probar con ids de `/products/{id}/items` | Habilita la estimación por reseñas |
| 4 | ¿`/questions/search?item={id}` funciona con publicaciones ajenas? | Ídem | Señal de interés por publicación |
| 5 | ¿Cuántas ofertas trae `/products/{id}/items` con `limit` y `offset` (hoy ~26)? | Paginar en un producto de celulares | Tamaño real de la muestra por producto |
| 6 | ¿`/products/search` tiene orden por relevancia estable para usar como **posición en catálogo** (C9)? | Repetir la misma búsqueda 3 veces en 3 días | Habilita o descarta C9 |
| 7 | ¿Qué trae `compatibilities` en `/catalog_domains/{id}` para repuestos? | Leer 3 dominios | Si sirve, repuestos pasa de Nivel C a B |
| 8 | ¿Para qué sirve `tier` en las ofertas? | Comparar `tier` contra reputación y destaque | Posible señal de destaque |
| 9 | ¿Cuántos pedidos por segundo aguanta el token de aplicación sin 429? | Subir de a poco hasta ver rechazos (tope 20/s) | Define el presupuesto del relevador |
| 10 | ¿`/sites/MLA/listing_prices` cambia por precio y tipo (clásica/premium/gratuita) y trae el cargo fijo por unidad? | Leer 10 categorías con 3 precios | Exactitud del techo de costo (N10) |
| 11 | ¿Hay productos de catálogo en las categorías hoja **de ropa** del dueño (MLA109096, MLA109104…) con otro texto de búsqueda? | Probar 5 búsquedas distintas | Si hay, la muestra de ropa deja de ser 0 |
| 12 | ¿`/categories/{id}` expone `children_categories` y `total_items_in_this_category` para **todas** las hojas, y cuántas hojas hay? | Recorrer el árbol completo | Presupuesto de llamadas de «todas las hojas» |

---

## Anexo B. Qué es verificado y qué es de terceros

- ✅ **Verificado por nosotros:** todo lo marcado con ✅ en las secciones 1, 3 y 4 (base de datos real, código, sondeo del 2026-10-13, análisis de la historia del 2026-10-21).
- 🔎 **De terceros (a tomar como pista):** descripciones de Nubimetrics, Real Trends y Crystal Zoom (sus propios sitios y comparativos con interés comercial); la composición 10 + 20 + 20 y la actualización semanal de las tendencias (documentación de UpSeller, **coherente** con nuestra medición); la presencia de `metrics.sales` y la composición exacta de la reputación (documentación de Mercado Libre que **no pudimos leer** por bloqueo de consulta automática: a confirmar con el sondeo).
- ❓ **Sin verificar:** términos de la API de Mercado Libre sobre guardar y agregar datos; Ley 25.326 aplicada al panel; el origen de datos de Nubimetrics y Real Trends; precios de todas las herramientas.

Fuentes consultadas: [Nubimetrics](https://www.nubimetrics.com), [módulo Mercado de Nubimetrics](https://www.nubimetrics.com/mercado), [módulo Competencia de Nubimetrics](https://www.nubimetrics.com/competencia), [Real Trends en argentina.gob.ar](https://www.argentina.gob.ar/node/222220), [CrystalZoom](https://www.crystalzoom.com), [UpSeller: Tendencias de Mercado Libre](https://www.upseller.com/es/help-doc-article-515), [Jaguar Sheet: alternativas a Nubimetrics](https://jaguarsheet.com/es/alternativas/nubimetrics).

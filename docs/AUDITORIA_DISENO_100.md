# 100 hallazgos y mejoras de diseño y experiencia (2026-10-21)

Hecho de noche, sin el dueño, recorriendo la app **en un navegador real con la cuenta real (solo lectura, ningún formulario enviado)**. La vara es la que pidió el dueño: que sea **práctica, bonita de ver y que se entienda sola**. Cada punto se mira con tres preguntas:
**¿Se ve bien?** (legible, ordenado, con el color donde hay que mirar) · **¿Se entiende solo?** (un nombre para cada cosa, el número importante primero, un botón principal) · **¿Se siente rápido y seguro?** (carga sin saltos, respuesta al tocar, poder deshacer).

Estado de cada punto: ✅ **hecho** en esta tanda (con prueba) · ⏳ **pendiente** (con propuesta concreta) · 💡 **propuesta de diseño** (gusto, no un defecto: va aparte, puntos 86–100).
Prioridad **A** conviene primero · **M** medio · **B** más adelante. Esfuerzo **S** horas · **M** 1-2 días · **L** más.
Los que dicen `UX200#nn` son del [`PLAN_UX_200.md`](../PLAN_UX_200.md) (2026-10-12) que **siguen sin hacerse**: acá se vuelven a medir y se priorizan. De los 85 defectos, **30 son pendientes de UX200 que se vuelven a medir** y **55 son hallazgos nuevos de esta noche**.

## Cómo se verificó (y qué se descartó)

Regla de la casa: ~25 % de lo que sale de una auditoría es falso. Se midió el DOM de **25 pantallas en escritorio (1366 px)**, **18 en celular (375 px)** y 8 en tema claro: tamaño de letra, contraste (cálculo WCAG con el fondo real de cada texto), áreas táctiles, encabezados, estilos sueltos, saltos de diseño al cargar (CLS), cómo se acomodan las tarjetas de números, campos sin etiqueta y alto de cada página; se leyeron el CSS (43 tamaños de letra, 21 niveles de z-index…) y las plantillas, y se miraron capturas para juzgar lo que un número no dice (orden, belleza, repeticiones). La landing se vio sin sesión en un servidor aparte.

**Se descartaron con evidencia** (no están en la lista): (1) capturas que mostraban una pantalla «en blanco» o «apagada» justo después de cargar: era la animación de entrada (`fadeInUp`, 0,45 s); con el DOM, a los 2 s todos los elementos estaban con opacidad 1 (pasó con Mercado, Cuenta, Planes, Stock masivo, Ventas manuales, Monitor y el checklist del Dashboard en tema claro); (2) «blanco sobre botón violeta 1,01:1» en el tema claro y «RECOMENDADO 1,04:1» en Planes: el fondo es un degradé que la medición no ve; (3) «los avisos no se anuncian a lectores de pantalla»: sí se anuncian (`role="alert"` / `role="status"` en cada aviso); (4) «Salud de la cuenta 67 en verde está mal»: el umbral de «Bien» es 65; (5) «campos sin etiqueta»: **0 de 11 pantallas** tienen un campo sin nombre accesible (218 en Costos); (6) scroll horizontal: **0 en las 18 pantallas de celular**; (7) peso de los estáticos: ya salen con Brotli y `immutable` (el CSS de 71 KB viaja en 20 KB).
**Lo que está bien y no hay que tocar:** la landing (clara, con datos de ejemplo rotulados), las cifras con dígitos tabulares, las fuentes propias, la animación de la barra del mes, las tarjetas de «Lo que tenés que hacer hoy» (la mejor pieza de la app), el tema claro (pasa el contraste), el trabajo de celular de las olas anteriores (letra ≥ 12 px en 15 de 18 pantallas) y la estabilidad al cargar (CLS ≈ 0 salvo el hero del Dashboard).

**Lo ya hecho esta noche** (catorce correcciones hechas al mirar las pantallas y el código, cada una con su prueba): D1 a D4, D19, D40, D41, D47, D49, D50, D60, D70, D77 y D78. Commits: `428385e` y `66c102c` (y los que siguen). Sin desplegar: lo hace el dueño con `python desplegar.py`.

### Si solo se hacen 10 (en este orden)
1. **D13** los campos casi no se ven (borde 1,03–1,08:1 contra el fondo).
2. **D12** un solo piso de 12 px para la letra en escritorio (hoy el 36 % del texto está por debajo; con un token alcanza).
3. **D24** Costos apila 4 herramientas con 4 botones principales.
4. **D56** Costos pide un «Aplicar» por modelo (218 campos): guardar al salir del campo.
5. **D25** el selector de período de Ganancia Real: aplicar al elegir, sin «Ver período».
6. **D5 + D6** una cifra, un lugar: el Dashboard repite 3 veces el facturado de 14 días y cada primer KPI repite el hero.
7. **D29** las tarjetas de números que quedan «huérfanas» entre 1024 y 1280 px.
8. **D61** Promociones: 7 filas casi iguales → una por modelo.
9. **D7** el modo privacidad no tapa los gráficos.
10. **D32** el botón violeta «Actualizar» fijo en la barra compite con el principal de cada pantalla.

---

## A. Números y mensajes que engañaban o se repetían (11)

1. ✅ [A·S] **Modo privacidad: dejaba a la vista 48 de los 57 montos del Dashboard** (la píldora de la barra, las tarjetas «Facturado − Costos = Te queda», el texto del hero, el detalle de cada misión): una lista fija de clases tapaba solo lo que alguien había marcado. Ahora `static/js/privacidad.js` recorre el texto de la página y le pone `monto-oculto` a todo elemento con «$ 1.234» o «US$ 12» (y un observador marca lo que se arma después): **57 de 57 tapados, 0 a la vista**, medido en el navegador. Los gráficos siguen aparte (D7). `tests/test_privacidad.py` (la lógica corre con node).
2. ✅ [A·S] **«Ventas hoy ▼ 86,3 % vs. ayer» en rojo a las 6 de la mañana**: se comparaba lo facturado HOY hasta ahora contra el día de AYER ENTERO, una falsa alarma cada mañana. Ahora dice «vs. ayer a esta hora» (el mismo criterio que ya usaba el hero) y no pinta flecha si ayer a esa hora no había vendido nada. `resumen_semanal.generar_resumen_dia`, `tests/test_resumen_del_dia.py` (6). Se borró de paso una rama de 7 días que nadie usaba y tenía otra ventana desfasada.
3. ✅ [M·S] **Calidad mostraba «100 / 100» en grande con «2 tienen mejoras pendientes» justo debajo**: el promedio real era 99,87 y se redondeaba hacia arriba. Ahora nunca dice 100 si alguna publicación no llegó. `calidad.promedio_de_puntajes`, `tests/test_calidad_grupos.py` (6 casos).
4. ✅ [M·S] **Planes (página pública): con la sesión iniciada la barra decía «Mi cuenta» con la inicial «M»** y el menú se armaba sin las capacidades de la cuenta (mostraba lo que en las demás pantallas está oculto). `app._inyectar_cuentas_usuario` usa los ids de la sesión cuando la ruta no pasa por `login_requerido`. `tests/test_paginas_publicas.py`.
5. ⏳ [M·S] **El mismo número varias veces en la misma pantalla.** Dashboard: «$5.986.713» (facturado de 14 días) 3 veces —tarjeta, cascada y título del gráfico— y «$2.342.572» 2 veces; Cobros: el hero ($6.514.727) y «Próximos 30 días» muestran la misma cifra; Monotributo: el «81 %» está en el aviso verde y otra vez en el medidor. → una vez cada cifra; el segundo lugar muestra otro dato o desaparece (UX200#7 cubrió «hoy», faltan los 14 días).
6. ⏳ [M·S] **El primer KPI repite lo que el hero ya dijo.** Opiniones: «4,68» arriba y de nuevo en la tarjeta «Calificación»; Calidad: «13 de 15 al 100 %» en el hero y en «Al 100 %»; Embudo: «Qué arreglar primero 2» y «Para revisar ficha 2». → cambiar ese KPI por un dato nuevo (p. ej. la tendencia) o sacarlo.
7. ⏳ [M·M] **Modo privacidad y gráficos:** los gráficos son `canvas`, no texto, y no tienen regla en `html.modo-privacidad`: los ejes («$12.000.000», «$400.000») y los tooltips quedan a la vista. → ocultar las marcas del eje de dinero y reemplazar el tooltip por «•••» mientras el modo esté prendido (Chart.js: `ticks.display`, volver a dibujar al alternar).
8. ⏳ [M·S] **Mercado: «Sin publicación tuya con esto» se repite en cada fila** de «Búsquedas en alza» (una pastilla gris por búsqueda). → una línea arriba («Ninguna de estas búsquedas coincide con tus publicaciones») y marcar solo las filas que sí coinciden, con color: ahí está la información.
9. ⏳ [M·S] **Los títulos largos se cortan en la parte que todos comparten.** «Últimas ventas» (Dashboard): las 8 filas dicen «Campera De Jean Hombr…» y solo se distinguen por el talle; en «Qué arreglar primero» (Embudo) y en Promociones el talle («M», «L», «XXL») queda enterrado en el medio del título. → modelo + variante («Negro · XXL») en vez del prefijo repetido; el título completo, al tocar.
10. ⏳ [B·S] **Monotributo muestra dos tarjetas seguidas con la misma letra «H»** («Categoría según tu facturación» y «Categoría declarada») cuando coinciden. → una sola, «Tu categoría: H · coincide con la que informaste a ARCA»; si no coinciden, ahí sí las dos.
11. ⏳ [M·S] **El hero dice una cosa y la barra otra.** «Llevás $28.080: más que ayer a esta hora ($16.955)» y justo abajo la barra «Hoy $28.080» contra «Promedio diario (14 d) $167.327», donde hoy parece ir al 17 %. Dos comparaciones distintas en la misma tarjeta. → hasta las 18 h la barra de referencia es «ayer a esta hora» (como el texto) con el promedio como marca fina; después, el promedio.

## B. Legibilidad: tamaño de letra y contraste (12)

12. ⏳ [A·S] **El 36 % del texto de escritorio mide menos de 12 px** (1.410 de 3.907 fragmentos en 20 pantallas): Stock masivo 62 %, Precios 55 %, Monitor 55 %, Costos 46 %, Stock 46 %, Dashboard 44 %, Embudo 44 %. **Casi 9 de cada 10 son 11,3–11,9 px**: `0.8em` / `0.82em` / `0.78em` de una base de 14,5 px. En celular ya se cumple (`movil.css`). Hay 72 declaraciones en el CSS **y unas 160 escritas a mano en las plantillas** (`style="font-size:0.82em"`), así que un token en el CSS no alcanza: conviene hacerlo junto con D39 (sacar los estilos sueltos). → `--text-xs: max(12px, 0.82em)` y usarlo en todas; es un cambio de 1-3 % de ancho, sin tocar el look.
13. ⏳ [A·S] **Los campos casi no se ven: el borde mide 1,03–1,08:1 contra el fondo** (218 de 218 campos de Costos; todos los de Precios, Calculadora, Ventas manuales, Promociones). WCAG pide 3:1 para reconocer un campo. → borde de `input/select/textarea` más claro (≈ `#5b5b68` sobre el grafito); las tarjetas pueden seguir con su borde casi invisible (Design System v2).
14. ⏳ [M·S] **Unos 70 textos son de verdad chicos (9–10,7 px), solo en las 4 pantallas donde se midió el detalle:** 26 en el Dashboard, 35 en Stock, 5 en Precios y 4 en Costos (insignias del menú de 10 px, `subnav-tab-badge` de 10 px, pastillas `ux-pill` chicas de 10,2–10,7 px, tres de 9,5 px). → piso de 11 px para insignias y 12 para todo lo que se lee.
15. ⏳ [M·S] **Blanco sobre violeta: 4,23:1** (filtro activo «Todos / Activas / Clásica», contadores de 13–14 px en negrita, «Saltar al contenido»); AA pide 4,5:1. → un token `--accent-solid` ≈ 6 % más oscuro **solo para fondos con texto blanco**; el violeta de la identidad queda para bordes, íconos y texto grande. **Necesita OK del dueño: es un cambio de color.**
16. ⏳ [M·S] **Violeta como texto sobre oscuro: 4,09–4,37:1** (los puestos «#1…#31» de Mercado, los valores de KPI violeta de 16 px en celular, «ver todas», el texto de las fechas de Tendencias). → `--accent-text` más claro (≈ `#a78bfa`, ~6:1).
17. ⏳ [M·S] **Insignias rojas del menú y la campana: blanco sobre rojo 3,67:1** a 10–11 px. → 12 px en negrita o un rojo algo más oscuro.
18. ⏳ [M·S] **Píldora neutra: texto blanco sobre gris 2,56:1** («45 zonas» en Costos; los talles «L» ×6 en Calidad). → fondo más oscuro o texto oscuro.
19. ✅ [B·S] **El contador gris dentro del chip activo no se leía: 1,65:1** («Todos 2» en Día a día; 1,45:1 en tema claro). Ahora un `.text-muted` dentro de un `.btn` hereda el color del botón (`style.css`). `tests/test_correcciones_diseno.py`.
20. ⏳ [B·S] **Las estrellas vacías de Opiniones miden 1,16:1:** una calificación 4,68 se lee como «4 estrellas y nada». → contorno visible (3:1).
21. ⏳ [B·S] **En celular quedan 3 pantallas con letra < 12 px:** Calidad (14 textos), Embudo (12), Dashboard (11, `mini-list-variante` ×8).
22. ⏳ [M·S] **Hay 43 tamaños de letra distintos en el CSS** (`0.82em` ×39, `0.85em` ×33, `0.8em` ×24, `0.9em` ×19, `0.88em` ×11, `0.78em` ×9, `0.86em`, `0.92em`…) y dos fijos de 10 y 11 px. → seis niveles con nombre (`--text-xs/sm/md/lg/xl/2xl`) y que todo lo demás los use (UX200#121).
23. ⏳ [M·S] **Ningún párrafo tiene largo máximo** (no existe un solo `max-width: …ch`): el contenedor llega a 1.440 px y una línea de ayuda pasa de 150 caracteres en un monitor grande (lo cómodo es 60–80). → `max-width: 72ch` en subtítulos y párrafos de ayuda.

## C. Jerarquía y foco: qué miro primero (13)

24. ⏳ [A·M] **Costos apila 4 herramientas con 4 botones principales** («Subir la planilla completa», «Guardar y ver qué envíos resuelve», «Enviar» del chat de costos, «Agregar gasto»), repartidos a lo largo de 5.700 px en celular. La regla de la casa es uno por pantalla. → segmentos arriba: **Costos de fabricación · Gastos · Entrega Flex · Importar**, cada uno con su único botón principal.
25. ⏳ [A·M] **Ganancia Real: la barra de período tiene 5 atajos + un rango + «Ver período»** (7 / 14 / 30 días, Este mes, Mes pasado, 21 sep – 21 oct): son siete controles antes del primer número y hay que apretar un botón más para ver el resultado. → aplicar al elegir, el rango en una hoja, y el botón fuera (UX200#67/#101).
26. ⏳ [M·S] **Día a día: dos títulos serif seguidos** («Día a día» y «Despacho», mismo peso y tamaño). → el de la parte, más chico (UX200#10 quedó a medias).
27. ⏳ [M·S] **«✓ 6 pendientes» sale en rojo con una tilde de «hecho».** Una alerta con ícono de listo. → ícono de aviso, o sin ícono.
28. ⏳ [M·S] **La tarjeta de paquete en celular:** la foto (56 px) queda abajo a la izquierda con un bloque oscuro vacío arriba, y el título ocupa 4 líneas. → foto arriba y más grande (72 px) y título a 2 líneas con «…».
29. ⏳ [M·S] **Tarjetas de números huérfanas.** Entre 1024 y 1280 px de ancho, 7 grillas quedan con una sola tarjeta sola en la segunda fila: Dashboard (2 grillas, 3+1), Stock (4+1), Ganancia Real (5+1), Monotributo (4+1), Embudo (4+1) y el Monitor (3+1; a 4 tarjetas queda así en cualquier ancho cuando no hay publicidad). A 1366 px solo queda el Monitor. La grilla es `auto-fit` y no sabe cuántas hay. → una caja contenedora con `container-type` y reglas por cantidad (3 → 3, 4 → 4 o 2+2, 5 → 5 o 3+2, 6 → 3+3), o repartir la tarjeta sobrante a todo el ancho como ya se hace en celular.
30. ⏳ [M·S] **El borde de color de arriba de cada KPI no significa estado:** Calidad usa celeste, naranja, violeta y celeste; Stock violeta, dorado, verde y celeste; Promociones gris, naranja, celeste y naranja. El ojo busca un significado que no hay. → color solo cuando hay estado (verde bien, naranja atención, rojo urgente); el resto, neutro (UX200#123).
31. ⏳ [M·S] **Dashboard: «Completá tu perfil 6/7» ocupa el primer lugar, encima de la ganancia del día**, cuando falta un solo paso opcional. → debajo del hero, o una línea de 40 px (UX200#33).
32. ⏳ [M·S] **El botón violeta «Actualizar» de la barra aparece en las 25 pantallas** y compite con el botón principal de cada una (Descargar PDF, Gestionar, Promocionar…): dos violetas llenos en la misma vista. → ícono discreto con «actualizado hace 4 min» (UX200#114).
33. ⏳ [M·S] **Costos en celular: dos párrafos de ayuda (10 líneas)** antes de la primera tarjeta de modelo. → «¿Cómo se cargan?» plegado.
34. ⏳ [M·S] **Costos: «Subir la planilla completa» —la forma más rápida de cargar 100 costos— está al 61 % de la página** (a 3.477 de 5.703 px en celular). → arriba, junto al título (UX200#80).
35. ⏳ [B·S] **Día a día: «Cargá lo que te cobra tu logística →» se repite en cada paquete Flex** (naranja, una vez por tarjeta). → una sola vez, en el aviso de arriba del bloque.
36. ⏳ [B·S] **Costos: «Calculadora de comisiones» ocupa una fila entera bajo el título en celular**, y «Calculadora» ya es una sección del menú. → un link discreto o sacarlo.

## D. Color y sistema visual (11)

37. ⏳ [M·S] **21 niveles de `z-index`, hasta 10.000** (barra 50, menú 60, panel de avisos 70, barra inferior 90, chat 100, cajón 250, aviso de comentarios 300, burbuja 500, modo limpio 999, capa del menú en celular 8.590/8.600, buscador 8.700, tour 9.000/9.001, inactividad 9.500, avisos 9.999, «Saltar al contenido» 10.000). Nadie sabe qué va sobre qué. → una escala de 6 con nombre (`--z-barra`, `--z-menu`, `--z-panel`, `--z-modal`, `--z-aviso`).
38. ⏳ [M·S] **46 sombras, 35 transiciones y 13 radios de borde distintos.** → tres sombras, dos duraciones y cuatro radios (UX200#122).
39. ⏳ [A·L] **927 `style="…"` escritos a mano en 53 plantillas** (Tendencias 99, Ganancia Real 86, Dashboard 82, Costos 76, Calculadora 46) y 196–268 por pantalla ya armada. Hace que cada pantalla tenga su propia versión de lo mismo y es lo único que falta para la política de scripts estricta. El dueño pidió hacerlo después del celular, que ya terminó (UX200#120).
40. ✅ [B·S] **CSS muerto:** tres reglas de `#fondo-particulas` (`style.css`) de un canvas de partículas que ya no se incluye. Borradas; una guarda impide que vuelvan.
41. ✅ [B·S] **`transition: all` ×4 en `style.css`** (tarjeta de despacho, su círculo y la máscara y el anillo del tutorial): animaba también propiedades que no hacía falta. Ahora cada una lista las suyas (la máscara y el anillo del tutorial: `top/left/width/height`, que es lo único que mueve el JS). Guarda en `tests/test_correcciones_diseno.py`.
42. ⏳ [M·S] **Seis componentes de «etiqueta» casi iguales:** `badge`, `ux-pill`, `stat-chip`, `plan-badge`, `nav-badge` y `subnav-tab-badge`, cada uno con su tamaño, radio y relleno. → uno solo con variantes (UX200#128).
43. ⏳ [B·M] **La tipografía serif de los títulos pesa 122 KB** (fuente variable completa de 200 a 900) en la primera visita, solo para los `h1`, la marca y unos pocos títulos (pesos 700–800). → subconjunto de 2 pesos ≈ 40 KB. Inter ya está en 48 KB.
44. ⏳ [B·S] **Símbolos de texto donde van íconos:** ✓ ★ ✔ ✖ ▲ ▼ ↗ en 8 plantillas (11 «✓» escritos a mano en Planes) junto a íconos SVG de trazo. → un solo juego (UX200#124).
45. ⏳ [B·S] **El modal de confirmación se arma con 5 `style=` y un `z-index:9000` escritos en la etiqueta** (`base.html`): no hereda el tema ni la animación del resto de los paneles, y es lo único que no se puede ajustar desde el CSS.
46. ⏳ [M·S] **Tema claro: la marca (`.brand-mark`) pasa de dorada a marrón** (`linear-gradient(#92400e, #78350f)`): la identidad dice dorado para el logo. → un dorado oscuro que siga leyéndose dorado (`#b8860b` → `#9a6b00`). Es una decisión del dueño.
47. ✅ [B·S] **Las páginas de error (`errores.html`) no cargaban `fonts.css`:** se veían en la tipografía del sistema, no en la de la marca, justo cuando la persona ya está incómoda. Ahora cargan el CSS de fuentes (propio, sin base de datos). Queda pendiente que sigan el tema de la app y no el del sistema (usan su propia paleta con `prefers-color-scheme`).

## E. Celular y app instalable (8)

48. ⏳ [A·M] **Páginas muy largas en celular:** Ganancia Real 9.006 px (12,2 pantallas de scroll), Dashboard 6.176 (8,3), Costos 6.109 (8,3), Mercado 5.540 (7,5), Día a día 4.957 (6,7), Opiniones 4.457 (6). → pestañas «Hoy · Este mes · 14 días» en el Dashboard, «Ver 10 más» en Mercado, y los bloques de menor valor plegados (UX200#42/#65).
49. ✅ [M·S] **Áreas táctiles menores de 40 px en celular:** los tres chips de arriba de Día a día (37 px), las insignias de búsqueda de Tendencias (32 px), los chips de series del Monitor (29 px) y el link «Orden #…» de Cobros (17 px). Ahora miden 44 px (el link de Cobros, 39 px, con la zona de toque extendida sin mover nada), medido a 375 px sin desborde horizontal (`movil.css`). Queda «(Cambiar)» (un link dentro de una frase, que las normas dejan afuera).
50. ✅ [M·S] **Los botones de ordenar las tablas (`th-orden`) medían 19–20 px de alto** en Ganancia Real (también en celular) y en Stock. En celular ahora 44 px (`movil.css`); en escritorio quedan como estaban.
51. ⏳ [M·S] **78 `title="…"` (tooltips) que en celular no se ven:** varios son lo único que dice el nombre completo de un título cortado. → tocar para expandir.
52. ⏳ [B·S] **Landing en 375 px: la tarjeta flotante «2 publicaciones venden a pérdida» tapa parte de la maqueta del producto** (el encabezado «Ganancia Real · últimos 30 días» queda cortado).
53. ⏳ [M·M] **No hay `service worker`:** sin conexión se ve la pantalla de error del navegador, aunque la app se instala (`manifest.json`, `display: standalone`). → una página «Sin conexión: mostrando lo último que viste» y la caché de lo estático (UX200#151).
54. ⏳ [B·S] **El manifiesto no tiene `shortcuts`** (Despachar, Ventas de hoy) ni hay invitación a instalar la app (`beforeinstallprompt`: 0 usos). Para quien despacha desde el celular es el acceso más rápido.
55. ⏳ [B·S] **Landing: la página mide 8.970 px en celular** (13 pantallas) y «Funciones» sola ocupa 2.073. → cinco funciones en un carrusel o tarjetas de una línea con «Ver todas».

## F. Formularios y edición (5)

56. ⏳ [A·M] **Costos: 218 campos y un botón «Aplicar» por modelo.** → guardar al salir del campo con «Guardando… ✓ Guardado» al lado (UX200#79/#141); el botón queda solo para aplicar a todos los talles.
57. ⏳ [M·S] **Promociones → «Crear un descuento propio»:** el desplegable de publicaciones muestra títulos que empiezan igual y se cortan («Campera De Jean Hombre Negra Oscuro Clasica Rigido Pren…»), imposibles de distinguir. → un buscador con modelo + variante + precio.
58. ⏳ [M·S] **Suena un tono al guardar y otro al fallar, y no hay forma de apagarlo** (`global.js`: «sin toggle de silenciar»). En una oficina o de noche molesta. → una preferencia en Mi cuenta, apagada por defecto si el sistema pide menos movimiento.
59. ⏳ [M·M] **Calculadora: el formulario de 9 campos (1.130 px de contenido) vive en un panel `sticky` de 634 px con scroll propio** (se ve la barra de desplazamiento al costado) mientras el resultado queda vacío a la derecha. Scroll dentro del scroll. → que el formulario fluya y el resultado quede fijo (`position: sticky`) a la derecha.
60. ✅ [M·S] **Calculadora: el valor de ejemplo se leía como un valor cargado:** el campo grande del precio tiene `font-weight: 800` a 21 px y el placeholder («25000») lo heredaba, en negrita. Ahora el placeholder va en peso 400 (`ux.css`). (UX200#85; en Costos no se midió.)

## G. Gráficos y listas (4)

61. ⏳ [M·S] **Promociones: «Conviene promocionar 7» son siete filas casi idénticas** (mismo modelo, distinto talle, títulos de dos líneas). → una fila por modelo («Campera Jean Negra · 7 talles · $7,2 M inmovilizados») con «Armar promoción para los 7» (UX200#99).
62. ⏳ [M·S] **El día de hoy (a medias) se distingue en el gráfico de 14 días solo por un borde blanco.** → rotularlo «hoy (parcial)» con trama rayada (UX200#39).
63. ⏳ [B·S] **Monitor en vivo: la ganancia por hora es una línea que une horas sin ventas en $0** y con una sola venta dibuja un pico que parece una montaña. → barras (como las ventas) o puntos sueltos.
64. ⏳ [B·S] **El gráfico «Cómo viene octubre» termina sin rótulo:** la línea punteada llega a ≈ $11,8 M pero el número está en la tarjeta de arriba. → rotular el punto final.

## H. Navegación y estructura (5)

65. ⏳ [M·M] **Dashboard: «Personalizar» solo muestra u oculta** (0 elementos `draggable`): no se puede reordenar los paneles. → arrastrar y guardar el orden por cuenta (UX200#36).
66. ⏳ [B·S] **No hay atajos de teclado** más que Ctrl+K (0 combinaciones tipo `g d`). Quien usa la app todo el día lo nota (UX200#117).
67. ⏳ [M·S] **Ctrl+K vacío no muestra nada:** «Escribí para buscar publicaciones, secciones o acciones». → al abrir, las secciones y las 5 acciones más usadas, y las últimas visitas (UX200#110).
68. ⏳ [M·M] **La sección «Ventas y ganancia» tiene 6 pestañas** (Ganancia Real, Facturación, Cobros, Ventas fuera de MeLi, Reporte Fiscal, Monotributo) y la barra se corta en celular. → «Ventas fuera de MeLi» es una acción (un botón en Ganancia Real); «Reporte fiscal» y «Monotributo» van juntos en «Impuestos» (UX200#65).
69. ⏳ [B·S] **La campana muestra 1 fila («2 devoluciones por gestionar») y no dice que hay 6 pendientes ni tiene un enlace a la lista completa.** El menú dice 2, el Dashboard 6. → «2 de 6 · Ver todos» al pie del panel.

## I. Estados y respuesta: carga, error, deshacer (5)

70. ✅ [M·S] **La confirmación tenía siempre el botón rojo «Confirmar»**, aunque guardara 12 costos y no destruyera nada (`btn btn-danger` fijo): el rojo dejaba de significar peligro. Ahora el botón es violeta (acción) y rojo solo si se pide `peligro` (`confirmarDecision(mensaje, etiqueta, sub, true)`, 5.º parámetro de `confirmarAccion`): lo piden borrar una pregunta, eliminar un gasto o una venta, quitar un descuento, dejar de seguir un producto, desactivar un usuario y reemplazar los umbrales Flex. Verificado en el navegador con los dos tonos. `tests/test_confirmacion_tono.py` (la lógica corre con node; una guarda lista las destructivas y otra impide un rojo en «guardar/cambiar/aplicar»).
71. ⏳ [M·S] **Las dos píldoras de la barra dicen «Cargando…» en cada pantalla** (≈ 0,9 s en mis mediciones locales; menos en Fly) y cambian de ancho al llegar el dato. → guardar el último valor en `cache_db` y escribirlo ya en el HTML, y actualizar encima.
72. ⏳ [M·S] **El hero del Dashboard salta al cargar:** CLS 0,094 (el límite «bueno» es 0,1): 0,076 de un solo salto a los 3 s cuando llega la ganancia. Las otras 7 pantallas medidas dan ≈ 0. → reservar el alto del hero con un esqueleto.
73. ⏳ [M·M] **No existe «Deshacer» en ninguna parte** (0 usos en plantillas y scripts): despachar, ocultar, borrar un gasto, cambiar un costo. → un aviso de 8 s con «Deshacer» para lo reversible (UX200#116).
74. ⏳ [B·S] **Cuando Mercado Libre no responde, el Monitor dice «Mercado Libre no respondió» pero no ofrece «Reintentar».** Y salvo el Monitor (que muestra la hora) y el dólar de Preferencias, ninguna pantalla dice cuándo se trajo cada dato. → el texto + un botón de reintento, y «actualizado hace X» en cada tarjeta que sale de Mercado Libre (UX200#152).

## J. Accesibilidad (4)

75. ⏳ [M·M] **24 de 25 pantallas tienen un `h1` y nada más** (ningún `h2`): la persona que navega por encabezados no ve secciones; solo Día a día los tiene. → cada título de panel como `h2` (el estilo no cambia). UX200#157.
76. ⏳ [M·S] **Foco del teclado:** 8 reglas `:focus-visible` y 4 `outline: none` (cajón y menú, campos de atributo, campos en general, buscador). Los comentarios dicen que cada uno tiene un borde alternativo; falta recorrer cada pantalla con Tab y comprobarlo.
77. ✅ [M·S] **Movimiento reducido: el CSS ya apaga todas las animaciones** (`style.css:669`: `*{animation:none!important;transition:none!important}`), **pero lo que se mueve desde JavaScript la ignoraba**: el conteo de números del Dashboard (`animarNumeroHasta`, 650 ms) y cinco `scrollIntoView({ behavior: 'smooth' })` (`ux.js`, Stock, Precios, Promociones, Tendencias). Ahora todo mira `UX.prefiereMenosMovimiento()` / `UX.comportamientoDeScroll()`. `tests/test_movimiento_reducido.py` (la lógica corre con node y una guarda impide un `'smooth'` suelto). (Esta línea decía antes lo contrario —«3 bloques para 11 animaciones»—: se midió mal; el CSS ya las cubría.)
78. ✅ [B·S] **El diálogo de confirmación tenía `role="dialog"` y `aria-modal` pero ningún nombre:** el lector decía «diálogo» y no de qué. Ahora `aria-labelledby="modal-confirmar-texto"`.

## K. Textos y nombres (3)

79. ⏳ [M·S] **El nombre de la cuenta se escribe «Diegoarielsantiago» / «Noenoeindumentaria»** (el filtro `|title` sobre el apodo en mayúsculas de Mercado Libre) en la barra, el chat y la lista de cuentas, que además lo repite abajo en mayúsculas («DIEGOARIELSANTIAGO»). Parece un error de tipeo. → mostrarlo como Mercado Libre lo informa, una sola vez, y dejar elegir un «nombre del negocio» (ya existe el campo) (UX200#6/#184).
80. ⏳ [B·S] **Landing: el título de la pestaña dice «Gestión profesional para Mercado Libre» y el título para compartir dice «Cuánto te queda de verdad de cada venta»** (`<title>` y `og:title`). El segundo es el bueno. → el mismo en los dos.
81. ⏳ [B·S] **Pantallas con subtítulos genéricos** (Stock: «Qué tenés, dónde está y qué hay que reponer — se actualiza solo»; Precios: «El precio mínimo para no perder plata…»; Mercado: «Qué busca la gente…»): explican el nombre de la pantalla, no dicen cómo estás hoy. → la frase de resultado, como Ganancia Real y Cobros («Lo que realmente te queda…», «Plata que todavía te tienen que acreditar»). Va con el punto 89.

## L. Cuenta, planes y páginas públicas (4)

82. ⏳ [A·S] **Planes: Base y Elite son dos listas de frases con ✓**, sin una tabla que muestre la diferencia fila por fila (cuentas, consultas del asistente, soporte). → tabla comparativa y el «RECOMENDADO» sobre la columna (UX200#179).
83. ⏳ [M·S] **El layout no muestra cuántos días quedan de la prueba** (0 menciones de «prueba» o `trial` en `base.html`): hoy está en beta gratuita, pero el día que se cobre, la persona se entera al vencer. → una barra discreta «te quedan 9 días» solo con el cobro activo (UX200#182).
84. ⏳ [B·S] **Menú de cuenta: «Eliminar mi cuenta» está pegado a «Cerrar sesión»** en el mismo gris, a un clic de distancia. Tiene su propia pantalla de confirmación, pero lo destructivo y lo cotidiano no deberían ser vecinos. → moverlo a «Preferencias y datos», al final.
85. ⏳ [B·M] **Landing: sin testimonios ni imagen para compartir.** El `og:image` es el ícono de 512 px con `twitter:card = summary`: al pasar el link por WhatsApp sale un cuadradito. → una imagen de 1200×630 con la maqueta y la frase; y los testimonios de la beta, con permiso (UX200#187).

---

## M. Para que sea más bonito: propuestas de diseño (15) 💡

Esto no son defectos: es lo que haría con más tiempo para que la app **se vea y se sienta mejor**, apoyado en lo que se vio en las pantallas. Cada uno es chico y reversible; el dueño elige.

86. 💡 [M·S] **Fundido entre pantallas con una línea de CSS** (`@view-transition { navigation: auto }`, ya anda en Chrome, Edge y Safari 18): se cambia de pantalla sin parpadeo y se puede sacar el `fadeInUp` de cada panel (entrada de cada panel con retardo de 0,12–0,26 s). Hoy no hay ninguna transición entre páginas.
87. 💡 [M·S] **Esqueletos con la forma real** (hero, tarjetas, píldoras) en lugar de «Cargando…»: la persona ve dónde va a aparecer cada cosa. Hoy el único esqueleto es un texto gris.
88. 💡 [M·S] **Una miniserie (sparkline) dentro de las 4 tarjetas de números del Dashboard** («Ventas hoy», «Facturado · 14 días»…): ya existe el componente en 4 archivos. Da el contexto sin ocupar lugar.
89. 💡 [M·S] **Una frase-resumen en el título de cada pantalla**, como Ganancia Real («De $12.541.872 facturados, te quedaron $4.977.640 — el 39,7 %»): Stock, Precios, Mercado y Embudo hoy abren con una explicación en vez de un resultado.
90. 💡 [B·S] **Fotos de producto más grandes** (de 48 a 64 px) en rankings y listas, con esquinas iguales y vista ampliada al pasar el mouse (UX200#98).
91. 💡 [B·S] **Íconos de 16 px en las pestañas de cada sección:** el menú los tiene, las pestañas son solo texto.
92. 💡 [M·S] **Color por estado, no por tema:** tres tonos fijos (verde = bien, naranja = atención, rojo = urgente) y el violeta solo para acciones. Hoy un mismo violeta es «acción», «dato» y «decoración».
93. 💡 [M·M] **«Modo calmo» del Dashboard:** un interruptor que deja solo el hero y «lo que tenés que hacer hoy» (un solo scroll) para quien se abruma; el Dashboard completo tiene 14 bloques y 3.942 px.
94. 💡 [M·S] **Definiciones al tocar:** FULL, Flex, ROAS, ACOS, TACOS y «cargos de MeLi» con una línea de qué son (UX200#164).
95. 💡 [B·M] **Resumen de los lunes en la campana:** lo mejor, lo peor y una sola cosa para hacer (UX200#107).
96. 💡 [M·M] **Vacíos con ejemplo:** «así se va a ver cuando cargues costos» + el botón; para las cuentas nuevas, que hoy ven pantallas en blanco hasta la primera sincronización (UX200#149/#178).
97. 💡 [B·S] **Rótulos directos en el gráfico de 14 días** sobre el mejor y el peor día, en vez de una leyenda (UX200#131).
98. 💡 [M·S] **Tres acciones rápidas arriba del Dashboard** («Despachar», «Responder», «Cargar un costo»), con el número de cada una (UX200#43).
99. 💡 [M·M] **Una página interna `/ui` con todos los componentes y sus estados** (normal, foco, deshabilitado, error): sirve de guía de estilo viva, de prueba visual y evita que vuelvan las seis etiquetas (D42) (UX200#127).
100. 💡 [B·S] **Celebrar sin ruido:** cuando el día supera al de ayer a esta hora, una marca dorada discreta en el hero (el dorado ya está reservado para «momentos de ganancia puntual»); y cuando se carga el último costo que faltaba, un «¡Listo! Tu ganancia ya es real» con el número.

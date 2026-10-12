# 200 cosas para mejorar la UI y la UX de CoreLux (2026-10-12)

Cómo se armó: se recorrieron en un navegador real **14 pantallas en escritorio (1366 px) y 5 en celular (375 px)**, con la cuenta real, y se midió el DOM de cada una
(tamaños de letra, áreas táctiles, alto de página, estilos sueltos, títulos, accesibilidad). Lo marcado con ★ está medido, no opinado. Complementa a `PLAN_MEJORAS.md` y `PLAN_UX.md`:
**no repite lo ya hecho** (menú de 7 secciones, «Día a día» en una pantalla, tablas ordenables, plurales, fechas legibles, tema claro base). Cuando un ítem viejo sigue pendiente, lo cita (`PM#nn`).

**Cómo leerlo.** Cada ítem: `[prioridad · esfuerzo]` + qué se ve hoy → qué hacer.
Prioridad: **A** alto impacto, conviene primero · **M** medio · **B** bajo o para más adelante. Esfuerzo: **S** horas · **M** 1-2 días · **L** más.
Decisión de la persona: tachar lo que no se quiera; el resto se hace en el orden de las olas del final.

## Lo medido (la base de todo el plan)

| Pantalla (celular, 375 px) | Alto de la página | Textos de menos de 12 px | Áreas táctiles de menos de 40 px | Estilos escritos a mano en el HTML |
|---|---|---|---|---|
| Costos | **18.181 px** (22 pantallas de scroll) | 569 de 1.190 (48 %) | **302 de 362** (83 %) | 749 |
| Stock | **13.055 px** | 109 de 249 (44 %) | **107 de 122** (88 %) | 500 |
| Ganancia Real | 9.480 px | 90 de 302 (30 %); el más chico, **9,5 px** | — | 231 |
| Día a día | 6.303 px | 47 de 131 | 22 de 44 | 87 |
| Dashboard | 6.260 px | 115 de 259 (44 %); el más chico, 9 px | 8 de 45 | 195 |

Otros hallazgos medidos: **0** regiones `aria-live` (los avisos no se anuncian a lectores de pantalla) · solo **7** reglas `:focus-visible` en todo el CSS · casi ninguna pantalla tiene títulos `h2`
(saltan de `h1` a nada o a `h3`) · la barra superior en celular junta 6 controles y el resumen del día queda cortado («Hoy: 5 venta…») · el botón flotante de chat tapa contenido en celular.

---

## 1. Defectos visibles: corregir ya (10)

1. [A·S] ★ **Facturación: los montos se parten en dos líneas** («$1.040.7 / 35», «$480.39 / 5», «-$388.8 / 98») porque seis tarjetas entran en una fila con `minmax(150px)` y el valor es grande → tamaño de letra del valor según el ancho (`clamp`), nunca partir un número (`white-space: nowrap`) y abreviar («$1,04 M») cuando no entra.
2. [A·S] **Delta de 9,5 px** («▼ 30,5%» en Ganancia Real) es el texto más chico de toda la app → mínimo 12 px y misma altura que la píldora vecina.
3. [A·S] **El color de una variación no depende de si es bueno o malo.** En Publicidad, «Inversión ▼ 34,7%» sale en rojo, pero gastar menos no es malo → cada métrica declara si «subir es bueno» y el verde/rojo sale de ahí (costos y envíos al revés que ventas).
4. [A·S] **El botón flotante de chat tapa contenido en celular** (pisa el «Hacerlo →» del checklist y el borde derecho de las tarjetas) → que viva en la barra inferior o dentro de «Más», y si queda flotante, que se pueda minimizar y que el contenido tenga un margen inferior que lo respete.
5. [M·S] **Publicidad: «Contra el período anterior (—):»** muestra un «(—)» suelto → mostrar las fechas del período anterior o no mostrar nada.
6. [M·S] **El nombre de la cuenta sale en mayúsculas** («DIEGOARIELSANTIAGO», «NOENOEINDUMENTARIA») porque es el nickname de Mercado Libre; y en Planes el menú dice «Mi Cuenta» mientras en el resto dice el nombre → un nombre del negocio editable (`PM#102`) y el mismo rótulo en todas las pantallas.
7. [M·S] **Dashboard repite lo mismo tres veces:** «Facturado hoy» está en el hero y en la fila de KPIs, y «Resultado de los últimos 14 días» vuelve a explicar «facturado − costos = margen» → una sola vez cada cosa.
8. [M·S] **Costos muestra tres tarjetas en $0** (gastos fijos, variables, del período) cuando no hay gastos → un solo estado vacío con el botón «Cargar un gasto» (alquiler, sueldos, packaging).
9. [M·S] **Dos nombres para la misma pantalla:** pestaña «Calculadora MeLi», título «Calculadora de comisiones» → uno solo, sin la sigla.
10. [M·S] **Día a día tiene dos títulos seguidos con el mismo peso** («Día a día» y «Despacho»), más una frase de tres líneas que explica lo obvio → el segundo pasa a título de sección (`h2`), la frase se va.

## 2. Celular (22)

11. [A·M] ★ **Costos mide 18.181 px en celular.** Un acordeón por modelo con UN campo de costo («para todos los talles») y el detalle por talle detrás de «Ajustar por talle»; la lista de 70 publicaciones se agrupa por modelo y se pagina de a 10.
12. [A·M] ★ **Stock mide 13.055 px:** tarjetas compactas de una línea (foto, modelo, unidades, estado) que se expanden; las 22 «pausadas con stock» en una sola tarjeta plegada con la acción «Reactivar».
13. [A·S] **En Inicio lo primero es «Completá tu perfil 3/7»** y el número que importa (ganancia de hoy) queda a más de una pantalla de scroll → el hero arriba, y el checklist como una barra de una línea («Perfil 3/7 · Seguir»).
14. [A·S] **Los KPI se apilan a una columna** (en Stock, cinco tarjetas de ~135 px una sobre otra antes de ver nada útil) → grilla de 2 columnas con mini-KPI de ~80 px; los de menor valor, plegados.
15. [A·S] **Barra superior con 6 controles** (menú, buscar, resumen del día cortado, campana, actualizar, avatar) → sin el botón de menú (ya existe la barra inferior), el resumen del día en su propia fila deslizable o dentro de Inicio, y «actualizar» como ícono secundario.
16. [A·S] ★ **Letra de menos de 12 px en el 44 % del Dashboard y el 48 % de Costos** (mínimo 9 px) → piso de 12 px y 14 px para texto de lectura; las etiquetas en mayúscula de 11,6 px suben a 12.
17. [A·S] ★ **Áreas táctiles de menos de 40 px:** «Ver cuáles», los links «Hacerlo →», los chips de filtro, las casillas → mínimo 44×44 px (con relleno invisible si hace falta), separados 8 px entre sí.
18. [M·S] **Los ejes de los gráficos ocupan un cuarto del ancho** («$10.000.000») → «$10 M», «$500 k» en celular, y menos marcas en el eje.
19. [M·S] **Título + subtítulo en una fila que se parte mal** («Evolución mensual» en dos líneas y «costos vs. resultado neto · últimos 6 meses» al costado) → el subtítulo debajo, siempre, en celular.
20. [M·S] **La acción principal de cada fila queda a la derecha** (lejos del pulgar) → botón de ancho completo al pie de la tarjeta, o deslizar para actuar.
21. [M·M] **Selectores de escritorio en celular** (período, filtros, cuenta) → hoja inferior (bottom sheet) con opciones grandes.
22. [M·M] **Tablas que siguen siendo tablas en celular** (Facturación, Cobros, Reporte fiscal) → versión en tarjetas, como Stock y Ganancia Real.
23. [M·S] **La barra de pestañas de cada sección se corta** («Repu…») sin una pista clara → degradé en el borde, y que la pestaña activa se centre al abrir.
24. [M·S] **«Más» en la barra inferior** → una hoja con las secciones restantes, íconos grandes y un buscador arriba.
25. [M·M] **Gestos:** deslizar entre pestañas de una sección y tirar para actualizar en Día a día.
26. [M·M] **Barra de acción fija sobre la barra inferior** para lo principal de cada pantalla («Descargar etiquetas», «Guardar 3 cambios»), alcanzable con el pulgar.
27. [M·S] **Teclado correcto en cada campo** (`inputmode="decimal"`, `enterkeyhint`) y números con coma decimal; hoy los precios se tipean en un campo de número con flechitas.
28. [M·S] **iOS amplía la página al tocar un campo** si la letra es menor de 16 px (los campos de Costos y Stock masivo son de 12-13 px) → 16 px en celular, sin deformar el diseño.
29. [M·S] **Zonas seguras del teléfono** (`safe-area-inset`) en la barra inferior y en cualquier barra fija, para el iPhone con barra de gestos.
30. [B·M] **App instalable de verdad:** ícono y colores actuales, pantalla completa, arranque rápido con la «última foto» de los datos (`PM#118`).
31. [B·S] **Celular en horizontal (667×375):** revisar que gráficos y tablas aprovechen el ancho y la barra inferior no tape.
32. [B·S] **Respuesta táctil** al marcar un paquete como despachado (vibración corta si el navegador lo permite).

## 3. Dashboard / Inicio (12)

33. [A·S] **El hero primero, para todos;** el checklist «Completá tu perfil» se pliega solo cuando lo que falta es opcional, y tiene «Más tarde» que se recuerda por persona.
34. [A·S] **«Lo que tenés que hacer hoy» pinta botones de tres colores** (naranja, gris, violeta) sin criterio → un solo botón principal (el de más valor); el resto secundarios. El color de urgencia va en el borde de la tarjeta, no en el botón.
35. [A·M] **Cada pendiente con su plata en juego:** «68,7 % sin costo» → «tu ganancia puede estar inflada en ~$X»; ordenar por esa cifra.
36. [M·M] **Reordenar los paneles** (arrastrar) y guardar el orden por cuenta; hoy «Personalizar» solo muestra u oculta.
37. [M·M] **El hero cuenta solo el total del día** → una minilínea por hora comparando hoy contra ayer (y contra el promedio), para ver si el ritmo es bueno.
38. [M·S] **El gráfico de proyección del mes termina en el día 28** y el futuro queda en blanco → el mes completo con lo que falta sombreado y la línea del mes anterior punteada (ya está).
39. [M·S] **La barra de hoy (parcial) se distingue solo por un borde blanco** → rotularla «hoy (parcial)», con trama rayada.
40. [M·S] **«Salud de la cuenta: 80 · Bien»** no explica nada → tocar abre qué sumó y qué restó (el dato ya existe en el detalle del puntaje).
41. [M·S] **Dos nombres y dos fórmulas para el resultado** («Te queda», «Margen neto») en la misma pantalla → un solo término, una sola fórmula, y el detalle detrás de «Ver el detalle».
42. [M·M] **El Dashboard mide 6.260 px en celular:** pestañas «Hoy | Este mes | 14 días» en vez de apilar los tres bloques.
43. [M·S] **Acciones rápidas** («Cargar costo», «Responder pregunta», «Descargar etiquetas») en una fila fija debajo del hero.
44. [B·S] **«Actualizado hace 2 min»** junto al botón de actualizar, y un texto de ayuda en el ojo del modo privacidad (hoy es un ícono sin explicación).

## 4. Día a día: Despacho, Preguntas, Pendientes, Reputación (10)

45. [A·S] **Una barra pegada arriba con el resumen** («1 por despachar · 2 preguntas · 3 pendientes»), tocable para saltar a cada parte, en lugar del párrafo explicativo.
46. [A·M] **Marcar un paquete como listo:** hoy es un círculo naranja chico a la derecha → interruptor grande a la izquierda de la tarjeta, o deslizar para completar, con «Deshacer».
47. [M·S] **«Corte Flex: No configurado (Ajustar)»** es un link de 12 px dentro de una frase → un aviso accionable la primera vez («Contanos a qué hora cortás Flex») y, ya cargado, una cuenta regresiva «faltan 3 h 20 min».
48. [M·S] **Los dos botones del bloque de despacho** («Descargar 1 etiqueta en PDF» y «Traer ventas nuevas») compiten → el primero es el principal con el verbo «Imprimir etiquetas»; traer ventas es un ícono con «Actualizado hace X».
49. [M·S] **«Modo foco» aparece sin explicación** → una línea de ayuda la primera vez, se recuerda la elección y muestra de a un paquete con la foto grande.
50. [M·S] **Agrupar los paquetes** por tipo (Flex / Correo) y hora de corte, con encabezados fijos y contador por grupo (`PM#80`).
51. [M·M] **Preguntas:** respuestas guardadas con variables (`PM#82`), contador visible de los 350 caracteres, y junto a la pregunta la foto, el precio y el stock de la publicación.
52. [M·M] **Pendientes:** poder **posponer** uno por un día (o «ya lo resolví») y filtrar por tipo; hoy solo se resuelven.
53. [B·M] **Reputación:** el termómetro dice «cuánto margen tenés antes del límite» y una línea de 30 días con el evento que la movió.
54. [B·S] **Un botón «Volver arriba»** y la sección activa visible en la barra al scrollear (hoy se marca sola pero cuesta ubicarse en una página de 6.300 px).

## 5. Stock y Stock masivo (10)

55. [A·S] **«Pausadas con stock 22»**: la lista larga con casillas necesita una **barra de acción fija** que aparezca al marcar («Reactivar 3»), y que «Marcar todas» diga cuántas son.
56. [M·S] **Cinco KPI arriba, de los cuales tres casi nunca cambian** → Capital, Sin stock / por agotarse y FULL no disponible; el resto, plegado.
57. [M·M] **Vista por modelo** con los talles como una mini-curva (barras de stock por talle) en vez de una tabla plana: se ve de un vistazo qué talle falta.
58. [M·M] **Fecha estimada de quiebre** («se agota el 24 oct») junto a «Alcanza para N días», con color: 0 rojo, 1-2 naranja, 3-5 amarillo, más de 5 neutro, y una leyenda.
59. [M·S] **«Capital en stock» solo a precio de venta** → también a costo, con la diferencia (`PM#210`).
60. [M·M] **Stock masivo:** «Aplicar a todos los talles», «Sumar o restar N» y **deshacer el último guardado** (`PM#79`).
61. [M·S] **Antes de escribir en Mercado Libre,** un resumen («Vas a cambiar 12 publicaciones: 9 suben, 3 bajan») con las primeras filas y un botón «Confirmar»; ya hay un control de cambios, falta mostrarlo.
62. [B·S] **Exportar CSV:** elegir columnas y bajar en Excel con números en formato argentino (hoy el CSV sale crudo).
63. [B·M] **Lista de reposición** por proveedor con cantidades sugeridas, para compartir por WhatsApp.
64. [B·M] **Importar stock desde Excel** con una vista previa de lo que cambia.

## 6. Ventas y ganancia (14)

65. [A·M] **Tres niveles de pestañas en Ganancia Real** (las seis de la sección, las seis de «Más detalle» y los acordeones de adentro) y 9.480 px en celular → como máximo dos niveles; Reclamos y devoluciones pasa a su propia pantalla «Posventa» (`PM#220`).
66. [A·M] **La fórmula en una sola imagen:** de «Facturado» a «Te queda», barras horizontales que van restando comisión, envío, publicidad, costo y cargos mensuales (el componente viejo se borró por no usarse; se rehace limpio).
67. [M·S] **Selector de período** con «Este mes», «Mes pasado», «Este año» y «comparar con el anterior» activables (`PM#208`), aplicado al elegir, sin botón «Ver período».
68. [M·S] **«Distribución de márgenes»** («10 a 20 %: 5 % (1)») no se puede tocar → cada fila abre qué modelos son.
69. [M·S] **La curva de Pareto** tiene los nombres rotados e ilegibles → barras horizontales con el nombre completo recortado y su tooltip.
70. [M·S] **Facturación: «Tenés $105.618 de cargos pendientes de pago»** es un aviso sin salida → «Ver qué debés» con el detalle y la fecha límite.
71. [M·S] **Nombres técnicos en los KPI de Facturación** («Ganancia bruta real», «Percepciones (aprox.)», «Pagos cobrados −$388.898» con signo negativo) → palabras del dueño del negocio: «Lo que te queda de Mercado Libre», «Impuestos retenidos», «Lo que ya te descontaron».
72. [M·M] **Cobros:** un calendario semanal con barras por día de acreditación y el acumulado, en lugar de una lista.
73. [M·M] **Reporte fiscal:** vista previa tipo hoja del contador, descarga en Excel y PDF con un clic, y un sello «costo estimado» donde corresponde.
74. [M·S] **Monotributo:** la condición fiscal ocupa media pantalla aun después de declararla → ya declarada, el medidor primero (cuánto del techo usaste, cuánto falta en $ y en meses) y «cambiar condición» como un link chico.
75. [M·S] **Ventas fuera de MeLi:** carga de mostrador en 3 toques (producto, cantidad, precio) con teclado numérico.
76. [B·S] **«Cuándo vendés»:** mapa de calor con leyenda y la mejor franja destacada en una frase.
77. [A·S] **El sello de conciliación** («coincide al 99,7 % con lo que Mercado Libre depositó») sube al hero: es lo que más confianza da.
78. [B·M] **Comparar con el mismo período del año anterior** (`PM#209`) y un resumen en lenguaje natural («este mes ganaste 12 % más que el mes pasado, sobre todo por…»).

## 7. Precios y costos (12)

79. [A·M] **Costos: guardar al salir del campo,** con «Guardando… ✓ Guardado» al lado, en vez de pedir un botón por fila.
80. [A·S] **Importar costos desde Excel** con plantilla descargable, visible arriba de la lista (hoy está escondido).
81. [M·M] **Sugerir el costo** copiándolo de modelos parecidos («la Campera Azul 1 cuesta $12.000: ¿usar lo mismo?»).
82. [M·S] **Margen en vivo al tipear el costo,** coloreado según el margen objetivo de la persona, con el «precio mínimo para no perder» al lado.
83. [M·M] **Calculadora:** el resultado en una tarjeta fija a la derecha con «Te queda $X» enorme, y el botón «Usar este precio en la publicación…».
84. [M·S] **Calculadora inversa** («quiero ganar 25 % → ¿a cuánto publico?», `PM#197`) y Clásica / Premium lado a lado (`PM#198`).
85. [M·S] **Calculadora: los valores de ejemplo** (25000, 8000, 3500) se leen casi igual que uno cargado → placeholders claramente apagados, con la etiqueta siempre visible.
86. [M·S] **Precios: «Sin calcular 40»** es mayor que «30 analizadas» y casi no se nota → una barra de avance «30 de 70 con datos» y el botón para completar costos.
87. [M·M] **Precios: «Aplicar el recomendado»** por fila y en lote, con vista previa de margen antes y después y confirmación.
88. [B·M] **Historial de precios** como línea por publicación, con marcas de cada cambio y lo que pasó con las ventas después.
89. [B·M] **Cambiar precios por porcentaje** (+5 %) con tabla antes/después antes de aplicar.
90. [B·S] **Gastos fijos:** plantillas con un toque (alquiler, sueldos, monotributo, packaging) y el día del mes en que caen.

## 8. Publicaciones (8)

91. [A·S] **Calidad:** cinco filas con el mismo botón naranja «Ver cuáles» → un solo estilo, ordenadas por visitas que pierden, y el puntaje con meta («91 / 100: te faltan 9»).
92. [A·L] **Ficha única de publicación** con pestañas (Resumen, Ventas, Precio, Stock, Calidad, Opiniones, Preguntas, Historial) a la que lleve cualquier tabla (`PM#219`).
93. [M·M] **Opiniones:** resumen de lo que se repite en las quejas (tela, talle, color) y filtro por atributo (`PM#199`).
94. [M·S] **Embudo:** cada diagnóstico con una frase y su impacto estimado («~$X/mes si convierte como el promedio»).
95. [M·M] **Una tabla de salud por publicación** (semáforos de calidad, visitas, stock y margen) que reemplace a Calidad + Embudo + Opiniones (`PM#224`).
96. [M·S] **Agrupar por modelo en todas las listas,** con los talles dentro; y explicar «8 pares de publicaciones compitiendo» con un dibujito simple de la canibalización.
97. [B·S] **Detectar fotos pobres** (sin foto principal, muy chicas) y avisarlo con la miniatura.
98. [B·S] **Miniaturas más grandes al pasar el mouse** y, en celular, al mantener apretado.

## 9. Crecimiento: Promociones, Publicidad, Tendencias, Competencia (10)

99. [A·S] **Promociones: ocho botones «Promocionar» idénticos** (y el mismo modelo repetido por talle) → agrupar por modelo (`PM#188`) y un botón principal «Armar promoción para las 8», los demás secundarios.
100. [M·S] **Mostrar el margen que queda con el descuento** antes de promocionar (`PM#191`).
101. [M·S] **Publicidad:** el selector de período con «Ver período» violeta (un segundo botón principal) → que se aplique al elegir, sin botón.
102. [M·M] **Publicidad:** mini-tabla «los 5 que más gastan sin vender» con «Pausar» (con confirmación) y recomendación por campaña con impacto estimado (`PM#88`).
103. [M·S] **Tendencias: «Mucha competencia» en rojo** comunica «malo», pero es contexto → un tono neutro/celeste y una frase con qué hacer («compití con envío y reputación»).
104. [M·S] **Explorador de mercado con ejemplos que se tocan** («probá: campera puffer»).
105. [M·M] **Competencia:** aviso cuando un rival baja el precio (`PM#93`) y un gráfico de líneas con tu precio encima.
106. [M·S] **Crecimiento tiene tres pestañas** (Promociones, Publicidad, Tendencias) y Competencia vive aparte → integrarla o dejarla visible cuando la cuenta tiene catálogo.
107. [B·M] **«Esta semana en tu negocio»:** una tarjeta de lunes en Inicio con lo mejor, lo peor y una sola cosa para hacer.
108. [B·S] **Cada recomendación con «¿por qué me lo decís?»** que muestre el dato que la origina.

## 10. Navegación y estructura (10)

109. [M·S] **Migas de pan** en pantallas profundas y un «volver» que respete de dónde se vino (`PM#105`).
110. [M·M] **Ctrl+K:** resultados agrupados (pantallas, publicaciones, acciones), atajos visibles y recientes (`PM#103`); también buscar una venta por número de orden.
111. [M·S] **«MÁS USADO» en cada sección** (Stock, Ganancia Real, Costos, Publicidad, Calidad): con pocos usuarios es ruido → mostrarlo solo cuando sale del uso real de esa persona.
112. [M·S] **Selector de cuenta bajo el logo:** mostrar el nombre del negocio, el plan y «Agregar cuenta» ahí mismo.
113. [M·S] **Dos píldoras en la barra** («Hoy: 5 ventas · $197.202», «Depósito: $60.198 · 26 oct») con letra de 11,6 px → una sola con un panel de detalle al tocar.
114. [M·S] **El botón violeta «Actualizar» en todas las pantallas compite con la acción principal** (`PM#99`) → ícono discreto con «Actualizado hace X».
115. [M·M] **Enlaces profundos desde la campana:** llevar a la fila exacta, ya resaltada (scroll + pulso breve).
116. [M·M] **Deshacer global:** un aviso con «Deshacer» durante 8 segundos para lo reversible (despachar, ocultar, mover).
117. [B·S] **Atajos de teclado** (`g d` Día, `g s` Stock, `?` ayuda) con una hoja que los lista.
118. [M·S] **Recordar período y filtros por pantalla** y mostrarlos como chips con ✕ («Últimos 14 días ✕», «Solo Flex ✕»).

## 11. Sistema visual (10)

119. [A·S] **Reglas de botones, en el sistema y en una prueba:** primario violeta, secundario gris, destructivo rojo; naranja y verde son ESTADOS, no botones.
120. [A·L] ★ **Estilos escritos a mano en el HTML** (749 en Costos, 500 en Stock, 231 en Ganancia Real) → clases del sistema: da consistencia, achica las páginas y es el paso que falta para la política de seguridad estricta (`PM#110`).
121. [M·S] **Una escala de letra** (12 / 14 / 16 / 20 / 28 / 40) en variables y usarla en todo; hoy se pisan tamaños sueltos en cada pantalla.
122. [M·S] **Escala de espacio de 4 px** (4 / 8 / 12 / 16 / 24 / 32) y radios y sombras en tres niveles.
123. [M·S] **El borde superior de color en los KPI** se usa en casi todos → reservarlo a los que tienen un estado (rojo = mal, verde = bien); el resto, neutro.
124. [M·M] **Íconos de un solo juego** (trazo 1,6 px; 16 / 20 / 24); quedan algunos emoji en textos y misiones (💀) que no combinan.
125. [M·M] **Recorrer el tema claro pantalla por pantalla** con una lista de contraste (`PM#125`) y ofrecer «igual que el sistema» como valor por defecto (`PM#215`).
126. [B·S] **Densidad cómoda / compacta** en Preferencias, para tablas y listas.
127. [M·M] **Una página interna `/ui`** con todos los componentes y sus estados (normal, hover, foco, deshabilitado, error): sirve de referencia y de prueba visual.
128. [M·S] **Cuatro estilos distintos de «etiqueta»** («MÁS USADO», «EN VIVO», «MUCHA COMPETENCIA», «TE DEJA GANANCIA») → un solo componente con variantes.

## 12. Gráficos y visualización (6)

129. [M·S] **Ejes y tooltips en formato argentino** y abreviados («$10 M»); el tooltip dice el día de la semana y la diferencia contra el promedio.
130. [M·S] **No depender del color:** barras de costo y resultado distinguibles también por patrón o etiqueta (daltonismo).
131. [M·S] **Etiquetas de «mejor» y «peor» día** directamente sobre las barras de 14 días.
132. [M·S] **Estado de carga y vacío dentro del gráfico** (hoy el recuadro queda en blanco unos segundos).
133. [B·M] **Compartir el resumen del día como imagen** (para WhatsApp), con la marca y sin datos sensibles si el modo privacidad está activo.
134. [B·S] **Una alternativa en texto de cada gráfico** («el mejor día fue el 07/10: $166.155»), útil también para lectores de pantalla.

## 13. Tablas y listas (6)

135. [M·S] **Mostrar qué columna está ordenada** (flecha) y recordar el orden elegido.
136. [M·M] **Filas que se expanden** en lugar de saltar a otra página, con el detalle por talle adentro.
137. [M·M] **Selección múltiple con una barra de acciones fija** («3 seleccionadas: Reactivar · Exportar»).
138. [M·S] **Un solo patrón de «ver más»** (hoy «Ver las 4 restantes», «Ver 12 más», paginados distintos).
139. [B·M] **Columnas configurables** (mostrar y ocultar) en Stock y Costos.
140. [B·S] **Buscador propio en cada tabla larga,** con las coincidencias resaltadas.

## 14. Formularios y edición (6)

141. [A·M] **Autoguardado con estado visible** («Guardando… ✓») donde se pueda; botón «Guardar» solo en lo que escribe en Mercado Libre.
142. [M·S] **Validación mientras se escribe** (precio fuera de rango, número con coma) con el mensaje debajo del campo.
143. [M·S] **Números con separador de miles al tipear** y aceptando coma o punto decimal.
144. [M·S] **Etiqueta siempre visible** (no solo placeholder) en todos los campos, y foco inicial en el primero.
145. [M·S] **Enter envía** el formulario simple y Esc cierra el panel.
146. [M·M] **Toda confirmación destructiva** con el efecto resumido («se quita el descuento de 3 publicaciones») y un «Deshacer» posterior.

## 15. Estados: carga, vacío, error, éxito (8)

147. [M·S] **Un esqueleto de carga único** para todas las pantallas (`PM#121`).
148. [M·S] **Error por sección con «Reintentar»** que recarga solo esa parte, sin perder lo demás.
149. [M·M] **Vacíos con ejemplo y salida** («así se va a ver cuando cargues costos» + el botón), para las cuentas nuevas (`PM#123`).
150. [M·S] **Éxito sin modal:** un aviso breve con la acción siguiente («Costo guardado · Ver cuánto ganás»).
151. [M·S] **Sin conexión:** una franja «Sin conexión: mostrando datos de hace 5 min».
152. [M·S] **«Actualizado hace X» en cada tarjeta que sale de Mercado Libre** (`PM#214`), con el botón de refrescar solo esa tarjeta.
153. [M·M] **Sincronización en curso:** una barra fina arriba con el avance («Trayendo ventas… 60 %») en lugar de números que cambian de golpe.
154. [M·S] **Cuando algo tarda más de 2 segundos,** decir qué se está haciendo («estamos trayendo tus anuncios de Mercado Libre»).

## 16. Accesibilidad (8)

155. [A·S] ★ **Cero regiones `aria-live`:** los avisos (toasts) y los cambios de estado no se anuncian → `role="status"` o `aria-live="polite"` en el contenedor de avisos y en los contadores que cambian.
156. [A·S] ★ **Foco visible en TODO lo interactivo:** hoy hay 7 reglas `:focus-visible` → un anillo uniforme de 2 px en botones, links, campos, pestañas y filas clickeables.
157. [A·M] **Títulos con jerarquía real:** casi todas las pantallas pasan de `h1` a nada o a `h3` → cada sección es un `h2` (y las subsecciones `h3`).
158. [M·S] **Contraste del texto secundario sobre tarjetas teñidas** (naranja, violeta, verde) medido con herramienta, no a ojo; ajustar los tintes que no llegan a 4,5:1.
159. [M·S] **Los gráficos con descripción accesible** (`aria-label` + la alternativa en texto del ítem 134).
160. [M·S] **Teclado completo:** flechas en las pestañas internas, Esc cierra paneles y menús, el orden de tabulación sigue al visual.
161. [M·S] **Movimiento reducido** bien respetado: hoy hay 3 reglas; revisar contadores animados, confeti y transiciones de página.
162. [M·S] **Texto grande del sistema y zoom al 200 %:** probar que nada se solape ni se corte (usar `rem` en vez de `px` en las letras).

## 17. Microcopy y contenido (8)

163. [A·S] **Un solo nombre para la ganancia:** «Te queda», «Ganancia neta real», «Margen neto», «Ganancia bruta real» y «Resultado neto» conviven → un glosario corto y usarlo en todas partes.
164. [A·M] **Jerga explicada la primera vez:** ROAS, ACOS, TACOS, FULL, Flex, «cargos de MeLi», «percepciones» → un «?» con una línea de definición (`PM#124`) y, donde se pueda, la palabra común.
165. [M·S] **Botones con verbo y objeto:** «Ver cuáles» → «Ver las 23 publicaciones», «Hacerlo →» → «Cargar el costo».
166. [M·S] **Sacar los subtítulos que repiten el título** («Qué tenés, dónde está y qué hay que reponer — se actualiza solo cada 4 minutos») o convertirlos en una ayuda corta.
167. [M·S] **Formato de números único:** pesos sin centavos, porcentajes con coma, «u.» para unidades, fechas «12 oct»; una prueba que lo revise en las plantillas nuevas.
168. [M·S] **Mensajes de error con causa y salida** (`PM#122`): auditar los de formularios y los de acciones sobre Mercado Libre.
169. [B·S] **Tono parejo:** voseo siempre, frases con el dato adentro, nada de «¡Genial!» ni signos de exclamación salvo logros.
170. [B·S] **Textos largos fuera de la pantalla** (términos, explicaciones) en una página de ayuda enlazada, no en un párrafo sobre los datos.

## 18. Onboarding, ayuda y retención (8)

171. [A·S] **Checklist de perfil:** el paso de más valor primero (costos) con lo que se gana («+$X de precisión») y fuera de la vista cuando solo quedan los opcionales.
172. [A·M] **Tour de 3 pasos que termina en la primera tarea real** («cargá el costo de tu modelo más vendido»), no solo en el menú (`PM#136`).
173. [M·M] **Ayuda contextual por pantalla:** un «?» con un GIF o video de 30 segundos.
174. [M·M] **Centro de ayuda con búsqueda,** accesible desde Ctrl+K (`PM#137`).
175. [M·S] **«Novedades»:** un aviso liviano después de cada deploy con lo nuevo y un link (`PM#142`).
176. [M·S] **Preferencias de avisos** (qué recibís, por dónde): lista para cuando se activen los mails.
177. [M·S] **«¿Te sirvió esta pantalla?» 👍 / 👎** en cada pantalla, con el comentario adjunto a la pantalla y la versión (el botón «Enviar un comentario» ya existe).
178. [M·M] **Cuenta nueva sin ventas:** datos de ejemplo claramente rotulados para ver cómo queda, hasta que llegue la primera sincronización.

## 19. Planes, cuenta y cobro (6)

179. [A·S] **Planes:** una tabla comparativa Base vs Elite fila por fila (✓ / —); hoy son dos listas de frases que no muestran la diferencia real.
180. [M·S] **Mostrar ciclo y próxima fecha de cobro** y el monto exacto, antes de pagar y en «Mi suscripción».
181. [M·M] **Cancelar con claridad:** una pantalla «qué pasa con mis datos» y un botón visible (no escondido), con la opción de pausar.
182. [M·S] **Barra discreta con los días que quedan de la prueba** («te quedan 9 días») cuando el cobro está activo.
183. [M·M] **Cambio de plan con una pantalla de confirmación:** qué se cobra, cuándo, y que no hay doble cobro (la lógica ya existe).
184. [B·S] **«Mi negocio»** dentro de Cuenta: nombre, logo y moneda, que reemplace el nickname en mayúsculas en todo el producto.

## 20. Landing y páginas públicas (6)

185. [M·M] **Una calculadora pública** («¿cuánto ganás de verdad por esta venta?», 3 campos y sin registro): es la mejor demostración.
186. [M·M] **Video o GIF de 30 segundos** de la app con datos de ejemplo (`PM#128`).
187. [M·S] **Prueba social** con testimonios de la beta, con permiso (`PM#126`).
188. [M·S] **Preguntas frecuentes** sobre seguridad (qué permisos pide Mercado Libre y por qué), precios y cancelación.
189. [B·S] **Comparación con la planilla de Excel** (`PM#131`), con el tiempo que ahorra.
190. [M·S] **Un único llamado a la acción repetido** («Probar 14 días gratis») y los tres pasos para ver tu ganancia en 2 minutos.

## 21. Rendimiento percibido (6)

191. [A·M] **Cargar primero lo de la base y después lo de Mercado Libre:** mostrar la pantalla con datos propios al instante y completar lo externo (hoy algunas pantallas esperan a la API).
192. [M·S] **Precargar la próxima pantalla** al pasar el mouse por el menú.
193. [M·S] **Tamaño fijo en las imágenes** y `loading="lazy"` para que la página no salte (Stock tiene 67 imágenes).
194. [M·M] **Renderizar solo lo visible** en las listas largas (Costos, Stock) para bajar los 18.181 px a lo que se ve.
195. [M·S] **Crear cada gráfico al entrar en pantalla** (en vez de todos al abrir).
196. [M·M] **Medir lo real:** `[Lento]` en los logs de producción (ya está) más LCP / INP / CLS de los usuarios reales, con una medición liviana y sin datos personales.

## 22. Medición y mejora continua (4)

197. [A·M] **Eventos mínimos y anónimos** (qué pantallas se usan, qué botones se tocan, dónde se abandona) para decidir con datos qué sigue de este plan.
198. [A·S] **Prueba de 5 segundos** con 5 personas reales por pantalla principal: «¿qué entendés?, ¿qué harías primero?».
199. [M·S] **Registrar los clics sin respuesta** (el mismo botón tocado tres veces) y los errores de JavaScript en `/admin/salud`.
200. [B·S] **Una pregunta de una línea** («¿qué tan fácil fue?») después de las tareas clave: cargar costos, descargar etiquetas, aplicar un precio.

---

## Cómo ordenarlo: cuatro olas

**Ola 1 · lo que se ve roto o roba confianza (1-2 días de trabajo, casi todo S).** 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 34, 45, 55, 77, 91, 99, 119, 155, 156, 163.
**Ola 2 · celular de verdad (la parte más grande y la que más impacta).** 11, 12, 18-29, 33, 42, 46, 79, 80, 86, 120, 141, 194.
**Ola 3 · claridad y confianza en los números.** 35, 40, 41, 65, 66, 67, 71, 74, 83, 87, 92, 94, 157, 164, 171, 172, 179, 191.
**Ola 4 · el resto, según lo que muestre la medición** (197-200 primero: sin datos de uso se prioriza a ciegas).

## Dos decisiones que necesito de vos

- **Ítem 120 (sacar los estilos escritos a mano):** es el cambio más grande en cantidad de archivos (casi todas las plantillas) y no cambia el aspecto; sí es el paso que falta para activar la política de seguridad estricta y deja las páginas más livianas. ¿Lo hago antes de la Ola 2 o después?
- **Ítem 111 (rótulos «MÁS USADO»):** hoy hay uno por sección; ¿los dejamos fijos, los calculamos por persona o los sacamos?

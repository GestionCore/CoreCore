# Plan de mejoras (2026-10-02)

Lista para armar el plan de acción. Cada ítem: **qué pasa → posible solución**. Prioridad: **A** antes de la beta · **M** durante la beta ·
**B** antes de vender a escala. Esfuerzo: S (horas) · M (1-2 días) · L (más). El dueño tacha las que no quiere; el resto se hace en ese orden.

Ya hecho en esta ronda (no hay que hacer nada): verificación de deploy que seguía redirecciones, pruebas de RLS que se salteaban en terminales
sin `DATABASE_URL`, respaldos con datos de todos los usuarios que entraban en la imagen de Docker.

## A. Seguridad y operación
1. [A·S] El respaldo del 1/10 vive dentro de la carpeta del proyecto (y viajó en las imágenes anteriores) → guardarlo fuera, cifrado; `respaldo.py` guarda por defecto fuera del repo.
2. [A·M] Respaldos manuales → respaldo automático semanal a un almacenamiento privado y cifrado; confirmar que Supabase tenga backups diarios.
3. [M·M] Sin Content-Security-Policy → agregar CSP (requiere sacar los `onclick` del HTML, ver 152).
4. [M·S] Chart.js desde un CDN sin verificación de integridad → servirlo desde `/static`.
5. [M·S] Fuentes desde Google → auto-hospedar Inter y Source Serif (más rápido y sin terceros).
6. [A·S] El limitador de llamadas a Mercado Libre usa Redis y en producción no hay: no limita nada → contador en memoria por proceso o en la base.
7. [M·S] El limitador de pedidos a CoreLux es por proceso (4 copias) → compartido vía `cache_db`.
8. [M·M] 20 cachés en memoria de módulo (ads, facturación, logística, tendencias…) → `cache_db` con vencimiento; `tendencias._categoria_cache` nunca vence.
9. [A·S] `ADMIN_EMAIL` sin cargar (dueño) → cargarlo; permitir varios admins.
10. [A·S] Sin monitoreo de caída → UptimeRobot/BetterStack sobre `/healthz/db` con aviso al celular (dueño).
11. [M·M] 286 `print()` → `logging` con cuenta y módulo; nivel configurable.
12. [M·M] 194 `except Exception` que solo imprimen → mandar a Sentry con contexto (cuenta, pantalla).
13. [M·M] CI de GitHub corre sin base: las pruebas de RLS nunca corren ahí → servicio Postgres en CI con migraciones y rol `app_backend`.
14. [A·S] `enter.py`/`enter.ps1` (script personal con pyautogui) están en el repo y en la imagen → sacarlos.
15. [A·S] Webhooks de MeLi sin configurar (dueño) → tildar temas y URL en el panel; baja el sondeo cada 4 min.
16. [A·S] Al vencer la prueba la persona queda en /planes sin poder pagar (Mercado Pago no está) → modo "beta" que extiende la prueba + botón "extender" en /admin.
17. [A·S] /planes y /suscripcion ofrecen pagos que no funcionan → en la beta mostrar "Beta gratuita".
18. [A·S] Referidos sin cobros que descontar → ocultar hasta que exista Mercado Pago.
19. [B·S] Sesión de 14 días sin "cerrar sesión en todos los dispositivos" → versión de sesión por usuario.
20. [B·S] El velo de inactividad a los 10 min puede molestar en un local → configurable en Preferencias.

## B. Sincronización y capacidad (medición real en producción: ~95 llamadas por cuenta cada 4 min)
21. [M·M] 41 consultas de stock de convivencia por ciclo (615 por hora por cuenta) → solo si cambió `last_updated` de la publicación o cada 30 min.
22. [M·S] 9 `GET /orders/{id}` por ciclo para el dinero retenido de reclamos abiertos → cada 1 h o al llegar un webhook de reclamos.
23. [M·S] 9 consultas "¿afecta la reputación?" por ciclo → una vez por día por reclamo abierto.
24. [M·M] 26 conexiones a la base por sincronización → agrupar escrituras por etapa.
25. [B·M] Todas las cuentas cada 4 min → frecuencia adaptativa (activas 4 min, inactivas hace días cada 30-60 min).
26. [B·S] Sin prioridad → primero las cuentas con alguien conectado.
27. [B·M] Tope actual ~64 cuentas por ciclo (2 en paralelo) → scheduler en una máquina aparte y más paralelismo dentro del tope del pooler.
28. [B·S] 1.425 llamadas por hora por cuenta → presupuesto global por app con freno ante 429.
29. [M·M] La sincronización inicial de cuentas grandes no muestra avance real → porcentaje real y entrar con datos parciales.
30. [M·S] Sin historial de cada sync (duración, llamadas, errores) → tabla + vista en /admin/salud.
31. [M·S] Si se cae el permiso de MeLi la persona se entera al entrar → aviso por mail y banner.
32. [B·S] Enriquecimiento con topes fijos → priorizar publicaciones activas con ventas.

## C. Exactitud de datos
33. [A·S] 35 ventas viejas con la hora de MeLi sin normalizar → `normalizar_horas.py --aplicar` (OK del dueño).
34. [M·M] Costo Flex sin conciliar con MargenFull ($378.250 vs $326.110) → revisar envío por envío con el dueño.
35. [M·M] Flex de productos menores a $33.000 (paga el comprador) sin modelar → modelarlo.
36. [A·S] Reputación: MeLi da las calificaciones como proporciones (0-1) y la pantalla las suma como cantidades ("1 calificación", "0%") → verificar con la respuesta real y corregir.
37. [M·S] Métricas del nivel sin umbrales → colorear con los límites oficiales de cada nivel y "te falta X para…".
38. [M·S] Tendencias usa la categoría raíz ("Ropa y Accesorios") y trae términos ajenos ("slots casino") → usar la categoría específica más vendida.
39. [M·S] Puntaje SEO dice "MeLi trunca a 60" y aun así da 100 a títulos de 98 caracteres → validar la regla vigente por categoría y que el puntaje la refleje.
40. [B·S] Escalas de Monotributo fijas → recordatorio en /admin en febrero y agosto.
41. [A·S] Facturación muestra un "te queda" ($5,6 M) distinto del de Ganancia Real ($3,9 M) → renombrar "después de MeLi y tus gastos" y enlazar a la ganancia real.
42. [M·S] Costo de fabricación faltante → cargarlo directo desde la tabla de Ganancia Real.
43. [B·M] Precio para ganar el catálogo armado sin datos reales → validarlo con una cuenta con catálogo antes de mostrarlo.
44. [M·S] Dinero retenido calculado con `in_mediation` → contrastarlo con Mercado Pago real.
45. [B·M] Sitio y moneda fijos (22 lugares con "MLA") → configuración por cuenta (Chile, México, Uruguay más adelante).
46. [B·S] Ventas reembolsadas archivadas sin pantalla → verlas y restaurar si fue un error.
47. [M·S] "Salud de la cuenta" (propio) y "Reputación" (MeLi) se confunden → explicar la diferencia o unificar.

## D. Dashboard
48. [M·M] 12 pedidos al cargar → un solo endpoint con todo (menos conexiones, más rápido).
49. [M·S] A la mañana la ganancia de hoy es $0 → comparar con "ayer a esta misma hora".
50. [M·S] Proyección del mes con 2 días de datos → mostrarla desde el día 5.
51. [M·S] Personalizar se guarda en el navegador → guardarlo por usuario (celular y PC iguales).
52. [B·S] Gráfico de facturación con alto fijo deja espacio vacío → que llene la tarjeta.
53. [M·S] Últimas ventas: toda la tarjeta lleva a Ganancia Real → cada venta abre su publicación/orden.
54. [M·S] Top productos con títulos cortados → miniatura y nombre del modelo sin talle.
55. [B·M] Ventas por provincia como lista → mapa de Argentina coloreado.
56. [M·S] Monotributo en el Dashboard y en su pantalla → en el Dashboard solo un aviso con link.
57. [M·S] "Lo que tenés que hacer hoy" y Logros son lo mismo con dos nombres → un nombre y una lista.
58. [B·S] Checklist al 100% desaparece sin más → celebración breve y ocultarlo.

## E. Ganancia Real y finanzas
59. [M·M] Ganancia Real pesa 286 KB y tarda ~3,6 s → secciones plegadas que cargan al abrir + caché de 5 min por cuenta y período.
60. [M·S] Tablas sin ordenar → ordenar por columna.
61. [M·S] Títulos que ocupan 3 líneas → una línea con "…" y completo al pasar el mouse.
62. [B·S] Cabecera de tabla que se pierde al bajar → fija.
63. [M·S] "PDF" usa imprimir del navegador → PDF prolijo o sacar el botón.
64. [B·M] Comparación con el período anterior solo en números → gráfico día a día de ambos.
65. [B·S] Punto de equilibrio aparece solo con gastos fijos → invitar a cargarlos con un ejemplo.
66. [M·S] Conciliación con lo depositado → listar las ventas que no cuadran.
67. [M·M] Costos es una página muy larga → pestañas: Fabricación · Gastos · Flex · Importar.
68. [B·S] Gastos con fecha de fin → aviso cuando vencen.
69. [M·M] Calculadora, Precios e Historial de precios son el mismo tema en 3 pantallas → "Precios" con pestañas.
70. [M·S] Precios: el número grande es un "✓" → mostrar cuántas cubren el margen.
71. [B·M] Cambio de precios guiado → vista previa del impacto en la ganancia del mes.
72. [B·M] Cobros como lista → calendario visual.
73. [B·S] Reporte fiscal solo en Excel → PDF para el contador.
74. [B·S] Ventas fuera de MeLi de a una → importar desde Excel.

## F. Stock y operación diaria
75. [M·S] El aviso de Stock aparece después de cargar (parpadea) → armarlo en el servidor.
76. [M·S] Tabla de Stock sin buscador ni filtros → filtros (sin stock, pausadas, FULL) y búsqueda.
77. [M·M] Días de stock restantes por modelo según la velocidad de venta.
78. [B·M] Cuánto reponer por talle según la curva de ventas.
79. [B·S] Stock masivo sin deshacer → deshacer el último cambio.
80. [B·S] Etiquetas de Despacho sin agrupar → por Flex/Correo y hora de corte.
81. [B·M] Marcar paquetes escaneando el código con el celular.
82. [M·S] Preguntas sin plantillas → respuestas guardadas.
83. [B·M] Respuesta sugerida → que use la ficha técnica y preguntas parecidas ya respondidas.
84. [M·M] Aviso cuando entra una pregunta (webhook → notificación).
85. [B·M] Calidad: mejoras simples en lote con link directo.
86. [M·S] Opiniones: aviso cuando llega una de 1-2 estrellas.
87. [B·S] Mensajes de compradores sin leer → en la barra superior.

## G. Crecimiento
88. [B·M] Publicidad: recomendación por campaña (subir/bajar presupuesto) con impacto estimado.
89. [B·S] ROAS por publicación también en Ganancia Real.
90. [M·M] Promociones: simular el margen antes de entrar en una promoción de MeLi.
91. [B·S] Tendencias: cómo leer competencia y concentración, con un ejemplo.
92. [B·M] Embudo contra el promedio de la categoría (si MeLi lo da).
93. [B·S] Competencia: aviso cuando un rival baja el precio.
94. [M·S] Logros: "Tu prioridad de hoy" repite la primera misión → mostrar el coach o nada.
95. [B·S] Racha, confeti y logros pueden verse poco serios → hacerlos opcionales.
96. [M·S] "Logística propia vs FULL" y Monotributo no están en el menú (solo por Ctrl+K) → agregarlos o integrarlos.

## H. Navegación
97. [M·L] 22 pantallas en 3 menús → ~12 con pestañas (decidir con lo que diga la beta).
98. [M·S] El menú está escrito dos veces (`base.html` y `nav_config.py`) → armarlo desde `nav_config`.
99. [M·S] "Sincronizar Todo" violeta en todas las pantallas compite con el botón principal → discreto, con "actualizado hace 2 min".
100. [M·S] Barra superior con 7 elementos chicos → 3 importantes; el resto al menú.
101. [B·S] Tema y modo privacidad repetidos en dos lugares → solo en el menú.
102. [M·S] Cuenta en mayúsculas ("DIEGOARIELSANTIAGO") → nombre del negocio editable.
103. [B·M] Ctrl+K → recientes, y buscar ventas por número de orden o comprador.
104. [M·S] Menús que abren con hover → que funcionen con teclado y con toque.
105. [B·S] Pantallas profundas sin "volver" → migas de pan.
106. [M·M] En celular el encabezado ocupa ~200 px → barra inferior de 4 pestañas y barra de estado plegada.

## I. Diseño y textos
107. [A·S] Texto tenue con contraste 3,1:1 (no se lee, lo marcaste en cosas.txt) → subirlo a 4,5:1.
108. [A·S] 92 textos de 10-11 px → mínimo 12 px.
109. [M·S] Violeta como texto sobre tarjeta 4,37:1 → tono más claro para links.
110. [M·L] 812 estilos sueltos en las plantillas → clases del sistema.
111. [M·S] Avisos flotantes (toasts) poco legibles y sobre la barra → fondo sólido, ícono y color por tipo.
112. [M·S] Ventana de confirmación con estilos sueltos → componente único (también Suscripción).
113. [B·S] Números que "cuentan" en cada carga → solo en el número principal.
114. [B·S] Efecto de onda en todos los botones → sacarlo o dejarlo solo en los principales.
115. [M·S] La página se desvanece al tocar un link (se siente lenta) → acortar o sacar.
116. [M·M] Gráficos con estilos distintos por pantalla → tema común de Chart.js.
117. [B·S] Íconos repetidos (el mismo en 4 pantallas) → uno distinto por pantalla.
118. [M·S] App instalable con colores viejos y sin service worker → actualizar manifest y hacerla PWA.
119. [B·S] Revisar favicon e íconos con la marca actual.
120. [M·S] La imagen al compartir el link es el ícono → tarjeta 1200×630 con la muestra del producto.
121. [B·S] Esqueletos de carga distintos en cada pantalla → componente único.
122. [M·S] Errores con texto técnico ("MeLi devolvió 403") → frase humana y qué hacer.
123. [M·M] Pantallas vacías de cuentas nuevas → ejemplo de cómo se va a ver y próximo paso.
124. [M·M] Términos difíciles (ROAS, TACOS, margen de contribución) → "?" con explicación corta.
125. [M·S] Tema claro revisado solo en Ganancia Real → recorrer el resto.

## J. Página de inicio y venta
126. [M·S] Sin prueba social → testimonios de la beta (con permiso).
127. [M·L] Sin demostración → modo demo con cuenta ficticia, sin conectar MeLi.
128. [B·M] Video o GIF de 30 s mostrando la app.
129. [B·M] SEO: sitemap, títulos y contenido ("cómo calcular la ganancia en Mercado Libre").
130. [B·S] Precios fijos en pesos con inflación → ajuste periódico.
131. [B·S] "Antes/después" frente a la planilla de Excel.
132. [M·S] Sin canal de consulta previo → WhatsApp o formulario.
133. [M·S] "Cómo calculamos tu ganancia" → página de transparencia.
134. [B·S] Sin medición de la landing → analítica respetuosa (Plausible).

## K. Onboarding, ayuda y retención
135. [M·S] Las 3 preguntas iniciales casi no se usan → usarlas (tutorial y orden del Dashboard) o sacarlas.
136. [M·M] El tutorial solo recorre el menú → guiar la primera tarea real (cargar costos).
137. [B·M] Centro de ayuda con artículos cortos por pantalla.
138. [M·M] Sin mails → bienvenida, "faltan costos", fin de prueba, resumen semanal.
139. [B·M] Resumen semanal también por mail/WhatsApp los lunes.
140. [M·M] Alertas por mail/WhatsApp (reclamo nuevo, stock por agotarse, pregunta sin responder).
141. [B·S] Encuesta de satisfacción a los 7 días.
142. [B·S] "Novedades" dentro de la app al desplegar algo.
143. [B·L] Usuarios adicionales (empleados) con permisos limitados.

## L. Administración
144. [M·M] /admin sin métricas del negocio → usuarios, activos 7 días, pruebas por vencer, cancelaciones.
145. [M·M] Ver la cuenta de un usuario en modo lectura para dar soporte (queda en auditoría).
146. [A·S] Extender la prueba con un clic.
147. [B·M] Embudo de activación (conectó → sincronizó → cargó costos → volvió al día 2).
148. [M·S] Errores de sync por cuenta en /admin/salud con "reintentar".
149. [B·S] Responder comentarios del canal de feedback por mail.

## M. Código y calidad
150. [M·L] `app.py` de 3.800 líneas y 129 rutas → blueprints por área.
151. [B·M] `global.js` de 1.500 líneas → módulos (barra, tutorial, búsqueda, chat, fechas).
152. [M·M] 125 `onclick` en el HTML → listeners (necesario para la CSP).
153. [M·M] Pruebas visuales automáticas de las pantallas principales con datos de ejemplo.
154. [M·M] Prueba de punta a punta del flujo nuevo (onboarding → sync → dashboard) con cuenta sintética.
155. [B·S] `particulas.js` sin uso → borrarlo.
156. [B·S] Documentos sueltos en la raíz (AUDITORIA, PLAN_*, cosas.txt) → a `docs/`.
157. [M·S] Validación de montos y fechas de formularios repartida → helper único.
158. [M·S] Prueba que exija política RLS por cuenta en toda tabla nueva.
159. [B·S] Prueba que exija que cada página del menú tenga su ícono y título (hoy se arregló a mano).
160. [B·S] Vistas previas para revisar diseño: script del proyecto que use una cuenta sintética (nunca datos reales).

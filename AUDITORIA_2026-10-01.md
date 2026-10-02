# CoreLux — 100 cosas para mejorar, implementar, quitar u optimizar

Auditoría del 2026-10-01 sobre el código (14.340 líneas de Python, 8.101 de plantillas, 125 rutas), la base de datos real, producción en
Fly.io y una prueba de humo de las 67 pantallas GET con una sesión real. Cada punto lleva la evidencia que lo respalda.

**Estado (actualizado):** ✅ hecho · ◐ parcial · sin marca = pendiente.

Leyenda — **Prioridad**: 🔴 alta (riesgo real hoy) · 🟠 media · 🟢 baja. **Esfuerzo**: S (menos de medio día) · M (1-3 días) · L (una semana o más).
**Tipo**: MEJORAR · IMPLEMENTAR · QUITAR · OPTIMIZAR.

---

## 1. Seguridad (1-14)

1. ✅ 🔴 M · MEJORAR — **No hay protección CSRF en las 41 rutas POST.** Entre ellas: precios y stock masivos (escriben en Mercado Libre), cambio de plan, cancelar suscripción, administración. Solo existe el `state` del OAuth. Agregar token CSRF (Flask-WTF/`itsdangerous`) o, como mínimo, verificar `Origin`/`Referer` en todo POST.
2. ✅ 🔴 S · MEJORAR — **GETs que cambian estado:** `/cambiar_cuenta/<id>`, `/sincronizar_hoy` y `/sincronizar_todo` (esta última bloquea la petición 26 s). Una imagen en cualquier sitio puede dispararlas. Pasarlas a POST.
3. ✅ 🔴 S · MEJORAR — **La cookie de sesión no declara `Secure`, `SameSite` ni `HttpOnly`** (`app.config` no tiene `SESSION_COOKIE_*`; el default de Flask es `SameSite=None`). Fijar `Secure=True`, `SameSite=Lax`, `HttpOnly=True` en producción.
4. ◐ 🟠 M · IMPLEMENTAR — **Faltan cabeceras de seguridad** (CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS). La CSP exige antes resolver el punto 55 (26 plantillas con `<script>` inline).
5. ✅ 🟠 S · IMPLEMENTAR — **Sin límite de pedidos en rutas públicas** (`/conectar`, `/callback`, los dos webhooks, `/r/<code>`). `rate_limiter.py` solo protege las llamadas salientes a MeLi (y usa Redis, que no existe en producción).
6. ✅ 🟠 M · IMPLEMENTAR — **Sin registro de auditoría** de acciones que escriben en Mercado Libre o cambian planes (precios masivos, stock masivo, cambio de plan desde `/admin`): quién, cuándo, qué valor antes/después.
7. ✅ 🟠 S · MEJORAR — **`/admin` usa `conexion_admin`** (salta RLS), contra la regla de CLAUDE.md que la limita a `token_manager.py`. Aceptable para un panel de dueño, pero hay que documentarlo como excepción y registrar sus accesos.
8. ✅ 🟠 S · MEJORAR — **El webhook de Mercado Pago no verifica la firma `x-signature`.** Hoy mitiga re-consultando el estado en la API (bien), pero sigue aceptando cualquier POST y llamando a MP por cada uno.
9. ✅ 🟢 S · MEJORAR — **El webhook de MeLi acepta notificaciones sin `application_id`** (se dejó por compatibilidad). Con las notificaciones ya llegando, exigirlo.
10. ✅ 🟠 S · MEJORAR — **`|safe` en `_ux.html`** (`titulo_html`, `sub_html`): seguro solo si cada llamador escapa lo externo. Auditar las llamadas con títulos de MeLi/compradores o escapar dentro de la macro.
11. ✅ 🟠 S · IMPLEMENTAR — **La sesión no expira** (no hay `PERMANENT_SESSION_LIFETIME` ni cierre por inactividad). Importante en computadoras compartidas del negocio.
12. ✅ 🟠 S · MEJORAR — **Mensajes de error que exponen la excepción** (p. ej. `facturacion_vista` devuelve `"No se pudo traer … ({e})"`). Mostrar un mensaje genérico y mandar el detalle a Sentry.
13. ✅ 🟠 M · IMPLEMENTAR — **Sin plan de rotación de `TOKEN_ENCRYPTION_KEY`** (cifra los tokens de MeLi). Pasar a `MultiFernet` para poder rotar sin desconectar a todos.
14. ✅ 🟠 S · MEJORAR — **Dependencias sin fijar ni escanear:** 10 paquetes con `>=`, sin `pip-audit` ni Dependabot. Fijar versiones y activar el escaneo.

## 2. Errores y estabilidad (15-27)

15. ✅ 🔴 S · MEJORAR — **Facturación: el detalle de conciliación da 422** (`detail_type=<charge>` inválido en `/periods/key/…/details`), así que el costo de almacenamiento FULL **nunca** se detecta. Corregir el parámetro.
16. ✅ 🟠 S · MEJORAR — **Publicidad: error 400 "no más de 90 días"** al pedir el gasto de Ads de un período largo (evolución de 6 meses, reporte anual). Partir en tramos de ≤ 90 días.
17. ✅ 🟠 M · OPTIMIZAR — **El coach de IA tarda 8 s y a veces devuelve respuesta vacía** (3 reintentos en la prueba). Cachearlo por día y degradarlo con elegancia (el timeout de 30 s ya existe; el problema son los reintentos por respuesta vacía).
18. ◐ 🟠 M · MEJORAR — **17 `except …: pass` silenciosos.** Cada uno esconde un error posible; como mínimo loguearlos.
19. ◐ 🟠 M · MEJORAR — **Las horas de venta están en UTC−4, no en hora argentina** (1 h atrasadas; una venta de 00:30 queda en el día anterior). Normalizar al ingresar y migrar el histórico en una sola operación.
20. ◐ 🟠 S · MEJORAR — **Despacho arma el día de despacho con `hora_venta` desfasada** (ver 19): las ventas de la franja del corte pueden caer un día antes. Revisar junto con el punto 19.
21. ✅ 🟠 M · MEJORAR — **`devoluciones_sync`, `sincronizador` y el webhook abren `conexion_usuario(usuario_id)` sin `cuenta_id`.** Con Plan Elite (dos cuentas) funciona por el modo de compatibilidad de RLS, pero no cierra el aislamiento por cuenta. Pasar siempre `cuenta_id`.
22. ✅ 🔴 M · MEJORAR — **Si el worker que tiene el scheduler cae, nadie lo retoma:** los demás workers decidieron al arrancar "otro lo tiene" y no reintentan el lock. La sincronización se detiene hasta el próximo reinicio.
23. ✅ 🟠 M · OPTIMIZAR — **El scheduler recorre las cuentas en serie cada 4 min** y APScheduler descarta la corrida si la anterior sigue. Con ~15 cuentas el ciclo ya no entra. Paralelizar y escalonar por cuenta.
24. ◐ 🟠 L · OPTIMIZAR — **25 cachés en memoria por proceso** (`_cache_*`). Con 2 máquinas × 2 workers hay 4 copias independientes: la caché casi no sirve y cada una es un riesgo de mezclar cuentas (ya pasó 12 veces). Moverlas a Flask-Caching con backend compartido o a la base.
25. ✅ 🔴 M · MEJORAR — **"Sincronizar Todo" bloquea la petición ~26 s** (GET `/sincronizar_todo`). Hacerlo asíncrono: devolver enseguida y mostrar progreso.
26. ✅ 🟠 M · IMPLEMENTAR — **Cargos de la factura que Ganancia Real no descuenta** (~$60.000/mes, 0,8 %): mantenimiento de eShop, "CSTP", cargos por devolución, almacenamiento FULL. Mostrarlos en Facturación y ofrecer sumarlos a costos fijos.
27. 🟢 S · MEJORAR — **El relleno de financiación y de pagos usa solo el primer pago de la orden** (`pago_id`). En órdenes con más de un pago el dato queda incompleto.

## 3. Rendimiento (28-39)

28. ◐ 🔴 M · OPTIMIZAR — **Cada página abre ~7 conexiones/transacciones** (middleware, contexto, tracking, token, la ruta…). Usar una sola conexión por petición guardada en `g`.
29. ✅ 🟠 S · OPTIMIZAR — **`set_config` se ejecuta dos veces por conexión** (usuario y cuenta): unirlo en una sentencia. Hoy la mitad de las 12-25 consultas por página son `set_config`.
30. ✅ 🟠 S · OPTIMIZAR — **El ticker hace 18 consultas cada 30 s por pestaña abierta.** Subir a 60-120 s, pausarlo en pestañas ocultas (Page Visibility), consolidar en 3-4 consultas y cachear 20 s por cuenta.
31. 🟠 M · OPTIMIZAR — **HTML muy pesado:** `/metricas` 283 KB (3,6 s), `/stock_masivo` 186 KB, `/costos` 170 KB. Paginar o cargar por demanda las tablas largas.
32. ✅ 🟠 S · OPTIMIZAR — **Los estáticos se sirven con `Cache-Control: no-cache`** aunque ya llevan `?v=mtime`. Usar `max-age=31536000, immutable`.
33. 🟠 M · OPTIMIZAR — **215 KB de CSS/JS sin minificar** (`style.css` 91 KB, `global.js` 80 KB, `ux.css` 43 KB). Minificar y partir `global.js` (tour, paleta Ctrl+K, HUD) para cargar cada parte solo cuando se usa.
34. 🟢 S · OPTIMIZAR — **Chart.js desde CDN en 5 páginas, sin `defer`.** Alojarlo localmente (versión fija) y cargarlo diferido.
35. 🟢 S · OPTIMIZAR — **Google Fonts remotas** (Inter, Source Serif, Space Mono): alojarlas localmente por velocidad y privacidad.
36. ✅ 🟠 M · OPTIMIZAR — **`/embudo_conversion` (2,4 s) hace 2 llamadas a MeLi por publicación** (visitas y preguntas). Las visitas ya están guardadas por el enriquecimiento; contar preguntas con una sola llamada.
37. 🟠 M · OPTIMIZAR — **`/despacho` (2,1 s) consulta `/shipments/{id}` por paquete en cada carga.** Guardar el estado y actualizarlo con el webhook de `shipments` (ya llega).
38. ◐ 🟠 S · OPTIMIZAR — **`cuentas_meli` acumula 270.000 lecturas secuenciales** (tabla de 1 fila que se consulta varias veces por petición: middleware, contexto, token, rutas). Guardar en la sesión (60 s) lo que se repite: cuentas, capacidades, plan.
39. ◐ 🟠 S · OPTIMIZAR — **`/api/calculadora_categorias` (1,7 s) y `/api/mensajes/sin_leer` (2,5 s en frío)** llaman a MeLi en cada visita. Guardar el resultado en la base con vencimiento.

## 4. Base de datos y datos (40-48)

40. ✅ 🔴 M · IMPLEMENTAR — **64 de 83 publicaciones (77 %) no tienen costo de fabricación**, y sin costo la ganancia queda inflada. Importar costos desde Excel/CSV con plantilla descargable y vista previa.
41. 🟠 L · MEJORAR — **Usar `family_id` como clave de "modelo"** en lugar de parsear el título (catálogo, stock masivo, costos, dashboard, despacho). Ya se guarda; falta migrar los consumidores.
42. 🟢 S · QUITAR — **`ventas.impuestos` está en el 100 % de las filas** pero ninguna pantalla lo usa. Confirmar y retirarlo, o usarlo.
43. 🟢 M · OPTIMIZAR — **61 publicaciones pausadas y 1 cerrada se sincronizan con la misma frecuencia que las activas.** Con miles de pausadas el sync se vuelve caro: sincronizarlas con menos frecuencia.
44. 🟠 M · IMPLEMENTAR — **Sin política de retención** para tablas que crecen sin fin (`tendencias_historial`, `navegacion_visitas`, `incidencias_posventa`, `ventas_retiradas`).
45. ◐ 🔴 M · IMPLEMENTAR — **Sin plan de respaldo probado.** Confirmar el plan de Supabase, hacer una restauración de prueba y programar un export lógico propio.
46. 🟢 S · MEJORAR — **Dueños de tablas mezclados** (`postgres` vs `app_admin`): obliga a pegar migraciones a mano. Unificar el dueño.
47. ◐ 🟢 S · QUITAR — **Migraciones duplicadas:** `migrations/` y `schema/migrations/`, más `_fix_migrations.py` y `01_schema_multitenant.sql` repetido en dos lugares. Dejar una sola fuente.
48. 🟠 M · IMPLEMENTAR — **Las migraciones se aplican directo a la base real.** Probarlas antes en una base vacía/staging con un job de CI.

## 5. Código y mantenibilidad (49-60)

49. 🟠 L · MEJORAR — **`app.py` tiene 3.595 líneas y 125 rutas.** Dividir en Blueprints (ventas, finanzas, catálogo, crecimiento, API, auth, admin).
50. 🟠 L · MEJORAR — **17 funciones de más de 80 líneas:** `calcular_ganancia_real` (259), `explorar_mercado` (184), `metricas_vista` (150), `callback` (131). Partirlas y probarlas.
51. ✅ 🟢 S · QUITAR — **20 imports sin uso** (`Response`, `stream_with_context`, `re`, `timedelta`…). Pasar `ruff`.
52. ✅ 🔴 L · IMPLEMENTAR — **0 tests automáticos.** Empezar por lo que toca plata: ganancia real, conciliación, precios mínimos, talle, cancelaciones, reclamos.
53. ✅ 🔴 M · IMPLEMENTAR — **Sin CI** (GitHub Actions): lint, tests, compilar las 38 plantillas Jinja y aplicar las migraciones en una base vacía en cada push.
54. 🟢 M · MEJORAR — **Código duplicado:** `limpiar_titulo_modelo_local` en `analisis_stock` y `tendencias`, helpers de caché, regex repetidos.
55. 🟠 L · MEJORAR — **26 plantillas con `<script>` inline y cientos de `style=` inline** (`tendencias` 98, `metricas` 78, `dashboard` 73, `costos` 52). Pasarlos a archivos estáticos y clases: habilita CSP, caché y baja el HTML.
56. ◐ 🟠 S · QUITAR — **Módulos muertos:** `simulador_costos.py` (nadie lo importa) y, mientras no haya Redis, `celery_app.py`, `tasks/` y `rate_limiter.py`.
57. 🟢 S · QUITAR — **Archivos de otras épocas:** `deploy/` (nginx/systemd), `Procfile` (Railway), `iniciar_corelux.bat`, `enter.ps1`, (`static/js/particulas.js` sí se usa: lo carga la landing).
58. ✅ 🟠 S · MEJORAR — **README desactualizado** ("Puerto de Santi Mens", "Flujo de Caja" que no existía). Reescribir: qué es, variables, arranque local, deploy, arquitectura.
59. 🟠 M · MEJORAR — **205 `print()` contra 10 llamadas a `logging`.** Pasar a logging con niveles y formato estructurado para poder filtrar en Fly.
60. ✅ 🟢 M · MEJORAR — **Sin type hints ni validación de configuración al arrancar** (`.env.example` omite `MP_ACCESS_TOKEN`, `SENTRY_DSN`, `REDIS_URL`, `CACHE_*`). Validar variables al iniciar y tipar los módulos de plata.

## 6. Operación y despliegue (61-70)

61. ✅ 🔴 S · IMPLEMENTAR — **19 commits sin subir a GitHub** (`main` va 19 adelante de `origin/main`): hoy el trabajo existe solo en tu PC y en la imagen de Fly. Subirlos y proteger `main`.
62. 🔴 S · IMPLEMENTAR — **Sentry no está configurado en producción** (falta `SENTRY_DSN` en los secretos de Fly): hoy no te enterás de los errores.
63. ✅ 🟠 S · MEJORAR — **El health check apunta a `/planes`** (página de 50 KB). Crear `/healthz` liviano que verifique la base.
64. 🟠 M · MEJORAR — **Producción no tiene Redis**, así que Celery y el rate limiter están inactivos aunque el código los espere. Decidir: sumar Redis (Upstash) o quitar esas piezas (ver 56).
65. 🟠 M · MEJORAR — **El scheduler corre dentro de la web.** Moverlo a un proceso/máquina propio (`[processes]` en `fly.toml`) para que un pico de tráfico no lo frene y para resolver el punto 22.
66. 🟠 S · MEJORAR — **2 máquinas con 2 workers cada una**: decidir si hace falta esa alta disponibilidad (consume 12 de las 15 conexiones y duplica costo).
67. ✅ 🟠 S · IMPLEMENTAR — **Las migraciones no corren solas en el deploy.** Agregar `release_command = "python migrate.py"` en `fly.toml`.
68. 🟠 S · IMPLEMENTAR — **Faltan secretos en Fly:** `MP_ACCESS_TOKEN` (sin él el cobro de suscripciones no funciona) y `SENTRY_DSN`.
69. 🟠 M · IMPLEMENTAR — **No hay entorno de pruebas (staging)**: toda prueba toca la base real.
70. ◐ 🟠 M · IMPLEMENTAR — **Sin monitoreo externo ni runbook:** un chequeo de disponibilidad (UptimeRobot) y una guía de qué hacer si el pooler se llena, un token vence o MeLi cae.

## 7. UX y diseño (71-86)

71. ✅ 🔴 S · IMPLEMENTAR — **Las páginas de error son las de Flask en inglés** ("Internal Server Error", sin menú). Agregar 404/500/403 propias, en español y con la marca.
72. 🟠 L · MEJORAR — **10 pantallas sin el rediseño UX v3:** admin, comparador de logística, conectar otra cuenta, error de conexión, onboarding, planes, reconectar, sincronizando, línea de tiempo de publicación y competencia.
73. 🟠 S · QUITAR — **Pantallas que existen pero no se enlazan desde ningún lado:** `/comparador_logistica`, `/publicacion/<id>/timeline`, `/publicacion/<id>/exportar_red`. Enlazarlas desde el detalle de la publicación o borrarlas.
74. ◐ 🟠 M · MEJORAR — **Accesibilidad:** 18 de las 38 plantillas sin ningún atributo `aria-`, una imagen sin `alt`, foco poco visible, la paleta Ctrl+K sin navegación completa por teclado.
75. ✅ 🟠 M · MEJORAR — **Probar el tema claro** en las pantallas nuevas (Calidad, Precios, Opiniones, Cobros, Dashboard): se verificaron solo en oscuro.
76. 🟠 M · MEJORAR — **Estados de carga y vacío no uniformes:** algunas pantallas usan `skeleton`, otras texto "Cargando…" o quedan en blanco si falla el fetch.
77. 🟠 M · MEJORAR — **Móvil:** las tablas anchas (stock masivo, costos) no usan `ux-tabla-cards` en todas partes. Revisar cada pantalla a 375 px.
78. ✅ 🟠 M · IMPLEMENTAR — **Checklist de primeros pasos con progreso** ("costos cargados 19 de 83", "Ads conectado", "cobros revisados") visible hasta completarlo.
79. 🟢 M · MEJORAR — **La búsqueda Ctrl+K encuentra secciones y productos pero no órdenes, preguntas ni reclamos.** Ampliarla.
80. ✅ 🟢 S · MEJORAR — **El modo privacidad (ocultar montos) tapa los números grandes, los KPI y las celdas de tabla, pero no los valores de los rankings (`ux-rank-valor`), las barras (`ux-dist-val`), los montos dentro de textos ni los gráficos.**
81. 🟢 S · MEJORAR — **Los widgets que elegís en el Dashboard se guardan solo en el navegador** (`localStorage`): no te acompañan a otro dispositivo ni a otra sesión. Guardarlos en la cuenta; de paso, el widget "Talles en riesgo de quiebre" tiene texto de indumentaria.
82. ✅ 🟢 S · IMPLEMENTAR — **Botón "ver el tutorial de nuevo"**: hoy se muestra una sola vez.
83. 🟠 M · MEJORAR — **Menú de 19 ítems en 3 grupos:** demasiado para un usuario nuevo. Mostrar un núcleo corto y el resto bajo "Más", según uso real y capacidades.
84. ◐ 🟠 M · IMPLEMENTAR — **Gráficos de comparación:** mes contra mes anterior y año contra año en Dashboard y Ganancia Real.
85. 🟢 M · MEJORAR — **Guía de estilo de textos:** unificar voseo y tono, y revisar frases que "protestan de más" o plantan dudas.
86. 🟢 S · MEJORAR — **Confirmaciones y "deshacer" no son consistentes** entre acciones destructivas (quitar descuento, dejar de seguir, eliminar gasto, cancelar suscripción).

## 8. Producto y funciones nuevas (87-100)

87. ✅ 🔴 M · IMPLEMENTAR — **No hay Términos, Política de Privacidad ni forma de borrar la cuenta.** Mercado Libre y Mercado Pago los piden para apps que manejan datos y cobran; además es obligatorio para vender la suscripción.
88. 🔴 L · IMPLEMENTAR — **Cobro por Mercado Pago sin terminar** (falta `MP_ACCESS_TOKEN`; no hay prueba de punta a punta; las cuentas de cortesía deben quedar excluidas de la facturación).
89. 🟠 L · IMPLEMENTAR — **Resumen diario por email o WhatsApp** (ventas, cobros, preguntas sin responder, reclamos). Hoy no hay ningún canal de salida.
90. ✅ 🟠 M · IMPLEMENTAR — **SEO y vista previa al compartir:** etiquetas Open Graph/Twitter, `robots.txt` y `sitemap.xml` para la landing.
91. 🟠 L · MEJORAR — **Preparar el uso fuera de Argentina:** `"MLA"` está fijo en 15+ lugares, la moneda es ARS y las zonas Flex solo cubren AMBA.
92. ✅ 🟠 L · IMPLEMENTAR — **Cambio de precios guiado desde `/precios`:** aplicar el precio recomendado con vista previa del impacto y confirmación (la acción masiva ya existe).
93. ✅ 🟠 M · IMPLEMENTAR — **Reactivar publicaciones pausadas que ya tienen stock** (61 pausadas hoy) con un botón y confirmación.
94. ✅ 🟠 M · IMPLEMENTAR — **Proyección del mes:** ventas y ganancia estimadas al ritmo actual contra el mes anterior.
95. 🟠 M · IMPLEMENTAR — **Comparador Clásica vs Premium por publicación** con la comisión real y el cargo de cuotas (ya se guarda el costo de financiación por publicación).
96. ✅ 🟠 M · IMPLEMENTAR — **Reporte mensual para el contador** con percepciones y retenciones de IIBB ya guardadas (hoy el fiscal es anual).
97. 🟠 M · IMPLEMENTAR — **Centro de notificaciones con historial** (nueva pregunta, reclamo, devolución, mensaje) alimentado por los webhooks que ya llegan.
98. ✅ 🟠 M · IMPLEMENTAR — **Panel de salud del sistema para el dueño:** estado del sync por cuenta, errores recientes, cuentas desconectadas, versión desplegada.
99. ✅ 🔴 M · IMPLEMENTAR — **Pruebas automáticas de aislamiento entre cuentas** (dos cuentas de prueba: ninguna pantalla ni API puede mostrar datos de la otra). Es el riesgo que más caro sale en un SaaS.
100. 🟢 L · IMPLEMENTAR — **Abstraer el canal de venta** (hoy todo asume Mercado Libre) para sumar Tiendanube u otros más adelante.

---

### Por dónde empezar (orden sugerido)
1. Hoy: **61** (subir a GitHub), **62** (Sentry), **3** (cookies), **71** (páginas de error). Son horas.
2. Esta semana: **1 + 2** (CSRF y GETs), **15**, **22**, **25**, **28 + 29**, **52 + 53** (primeros tests y CI), **87** (legales).
3. Luego: **40** (importar costos), **88** (cobro), **99** (aislamiento), **45** (respaldo).

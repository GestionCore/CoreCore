# PENDIENTES — leer primero al retomar (actualizado 2026-10-07)

Este archivo es la lista viva de lo que falta. CLAUDE.md lo referencia arriba de todo. Regla de oro (ver `memory/feedback_auditorias_externas.md`): **las auditorías externas traen ~25 % de puntos falsos o parciales**:
verificar cada uno contra el código, la base real (EXPLAIN, `pg_constraint`, conteos) o un navegador ANTES de tocar nada; arreglar lo real con un test que falle sin el arreglo; informar «corregido / endurecido / rechazado con evidencia».
Proceso acordado por Diego: **fase por fase**; respetar gevent, Postgres con RLS (aislamiento por `cuenta_id`), Fly.io (sin Redis), Jinja2 y JS vanilla (cero frameworks). Respuestas directas, sin introducciones largas.

## 0. Estado al cortar la sesión
- Producción (Fly `corecore`): commit `d5a451c` (auditoría de backend, 15 puntos) y commit **`5f6e6fe`** (auditoría de frontend, 19 puntos) están DESPLEGADOS y verificados: `/healthz` informa `5f6e6fed4dad` y las rutas clave responden. (Los commits de documentación posteriores no requieren deploy.)
- Migración `0038_indices_de_claves_foraneas.sql` ya está aplicada en la base real. La próxima migración libre es la **0039**. (La línea «Migraciones corridas hasta 0033» de CLAUDE.md está vieja: están aplicadas hasta la 0038; verificar con `python migrate.py --status`.)
- 632 pruebas pasan (también con `REDIS_URL=redis://localhost:6399/0`). Antes de cualquier deploy: ruff, pytest con y sin Redis (con el código de salida a la vista: nunca `;` ni `| tail` escondiendo el resultado).
- **Falta responderle a Diego el resumen final de los 19 puntos de frontend** (ver sección 2: qué se corrigió y qué se rechazó con evidencia). Lo que se rechazó: puntos 4, 5, 9, 13; parciales: 12, 17, 19. Un accidente a contar con honestidad: probando Stock masivo en el navegador local se disparó un `form.submit()` real
  contra el servidor local (usa la base de PRODUCCIÓN); llegó sin sesión, lo mandó a la portada y no cambió nada (la tabla `auditoria` no tiene ninguna fila de `stock_masivo`).
- Prueba en vivo del refresco de tokens NO se pudo hacer desde la PC: el `.env` local da `invalid_client` en MeLi (no gasta el refresh_token ni desconecta). Mirar los logs de Fly: un refresco por cuenta cada ~6 h, sin `invalid_grant`. La cuenta 7 quedó como estaba (se restauró su `expira_en`).

## 1. AUDITORÍA DE 52 PUNTOS (pegada por Diego el 2026-10-07): estado de cada uno
Leyenda: ✅ hecho y desplegado/commiteado · ◐ parcial/endurecido · ❌ rechazado con evidencia · ⏳ PENDIENTE (verificar antes de aplicar).

### FASE 1 — Integración con Mercado Libre (todo ⏳; Diego pidió ir «fase por fase», esta es la siguiente)
1. ⏳ Umbral de envío gratis: buscar `33000`/`33.000` y supuestos de piso en el código (`flex.py`, `precios.py`, `calculadora_costos.py`, textos). Usar `GET /users/{user_id}/shipping_preferences` (`free_shipping_min_ticket`) o `shipping.free_shipping` del ítem. Ojo: CLAUDE.md ya avisa que no se modeló el caso < $33.000 en Flex.
2. ⏳ Comisión en vivo: `GET /sites/MLA/listing_prices?price=&category_id=` para la calculadora (`/calculadora`, `calculadora_costos.py`). `precios.py` ya usa la comisión REAL por publicación (90 días) y no un % fijo: verificar qué otras pantallas multiplican porcentajes fijos. Cachear en `cache_db` (por categoría y rango de precio), nunca en memoria global.
3. ⏳ `/orders/search` con `offset > 1000` da 400: revisar `ventas_sync.py` (sync incremental desde `ultima_sincronizacion_ventas` con 2 h de colchón; relleno histórico de 540 días en `_completar_datos_*`). Si algún camino pagina profundo, usar ventanas `date_last_updated.from/to` (o `order.date_created`) que se achican.
4. ⏳ `catalogo_ganar.py`: la columna de «precio para ganar» a `JSONB` (migración **0039**, aditiva e idempotente). `/price_to_win` devuelve reglas por tipo de publicación y con/sin envío gratis. ⚠️ El panel se construyó solo contra la documentación (la cuenta de prueba no tiene catálogo): no hay una respuesta real vista; migrar guardando el JSON crudo y derivar el número en la lectura.
5. ⏳ Freno dinámico de rate limit: `auth/token_manager.llamar_api_meli` y `meli_http.py` deben leer `X-Rate-Limit-Remaining` / `X-Rate-Limit-Reset` (confirmar los nombres reales de las cabeceras con una respuesta de MeLi antes de codificar) y dormir con `gevent.sleep` (no `time.sleep` bloqueante). ⚠️ Estado en memoria compartido entre cuentas = la clase de bug #1 de CLAUDE.md: el límite es de la APLICACIÓN, no por cuenta; decidirlo y documentarlo. Reintentar 429 con backoff acotado.
6. ⏳ Corte de Flex dinámico: `GET /flex/sites/MLA/users/{user_id}/services` (ya se usa la ruta `/flex/sites/MLA/users/{id}/subscriptions/v1` en `flex.py`: sin `/shipping/`). Guardar horarios por día en `cuentas_meli.flex_info`; `despacho.py` (`hora_corte`) y `_dia_despacho.html` (`HORA_CORTE`, `pintarCuentaRegresiva`; ya usa `ahoraArgentina()`) tienen que leer el corte del DÍA que se mira.
7. ⏳ PUT con atributos obligatorios faltantes: en `publicacion_edicion.py`, `stock_meli.py` y `/actualizar_stock_multiple` (app.py ~2640) leer la causa del 400 (`cause[].code`/`missing_attributes`) vía `meli_errores.explicar_respuesta` y mostrar QUÉ atributo falta (con link a la publicación en MeLi). Toda escritura a MeLi tiene que mirar el resultado.
8. ⏳ Preguntas lentas: la auditoría habla de una tabla `preguntas_pendientes` — **verificar que exista** (hoy `_dia_preguntas.html` carga por fetch desde MeLi). Si hace falta persistir, columna `hora_limite_respuesta` (creación + 60 min, hora argentina) calculada al entrar el webhook de `questions`, y ordenar la cola por urgencia real. Verificar también la regla real de MeLi (tiempo de respuesta / horario comercial) antes de prometer «60 min» en pantalla.

### FASE 2 — Concurrencia y sincronización
9. ⏳ **Race de inventario en Stock masivo** (el más importante de esta fase): `/actualizar_stock_multiple` ya descarta lo que no cambió (`orig_<id>`), pero hace PUT absoluto sin leer antes. Hacer `GET` del ítem justo antes y, si `available_quantity` actual ≠ el `orig_` que vio la persona, NO escribir ese ítem y avisar «cambió mientras editabas (ahora X)». Los casos con variaciones reales se saltean a propósito (ver docstring). Mostrar el resumen por ítem: aplicado / saltado por cambio / falló.
10. ✅ Refresco de token con candado por cuenta (commit `d5a451c`; `tests/test_token_refresco.py`).
11. ✅ Timeout por defecto de 15 s en `llamar_api_meli`.
12. ✅ `UniqueViolation` en `vincular_cuenta_adicional` y `crear_o_actualizar_login`.
13. ⏳ Deadlock «Sincronizando…»: si la sync inicial falla, `sincronizacion_inicial_completa` queda `false`. `templates/sincronizando.html` + el chequeo de `auth/middleware.login_requerido`: timeout en el frontend (p. ej. 3 min), mensaje claro y botón «Reintentar» (POST auditado que relanza `sincronizador.sincronizar_todo` en segundo plano con `app._en_segundo_plano`); guardar el último error visible para la persona.
14. ⏳ Webhook como fuente primaria y barredora cada 30 min: ⚠️ **NO bajar el ritmo del `scheduler.py` (hoy 4 min) hasta confirmar que los webhooks de MeLi llegan de verdad**: falta, del lado de Diego, tildar los temas (`items`, `orders_v2`, `shipments`, `questions`, `claims`/`post_purchase`) y poner la Notification URL `https://corelux.app/notificaciones_meli` en MeLi Developers. Primero medir (`/admin/salud`, logs) cuántas notificaciones reales entran; recién ahí pasar el cron a 30 min. `antirrebote.py` ya junta ráfagas (1 sync por cuenta cada 15 s).
15. ⏳ Doble toque en Despacho: `toggleDespacho` (en `_dia_despacho.html`) manda el POST sin bloquear: bloquear el botón/tarjeta mientras dura la promesa (`pointerEvents = 'none'` o un flag por orden) y revertir bien si falla. Ahora los manejadores van por `data-click` (despachador de `ux.js`).

### FASE 3 — Base de datos y rendimiento
16. ❌ El `EXPLAIN` real muestra que las políticas RLS con `cuenta_id::text` SÍ usan `idx_ventas_cuenta_fecha` (el `OR` con constantes no cambia el plan). Si algún día hay muchos tenants, la mejora medida sería `cuenta_id = ANY(ARRAY(SELECT id FROM cuentas_meli WHERE usuario_id = …))`. No tocar sin medir con datos grandes y sin pasar `tests/test_rls_cuenta_activa.py`. (Comparar como TEXTO: castear '' a bigint explota.)
17. ✅ Índices de FK (migración 0038, aplicada); `referrals` ya los tenía. Una prueba exige que toda FK tenga índice.
18. ✅ Índice parcial de alertas sin `leida` (0038).
19. ❌ `ventas.codigo_postal` y `localidad` NO son huérfanas: 2.692 filas con valor y las usan `flex.py` y `ventas_sync.py` (hay un test que impide borrarlas).
20. ✅ Job horario `limpiar_oauth` en `scheduler.py` (borra pendientes de más de 15 min).
21. ❌ Nada marca `eliminado_en` (el borrado de gastos es físico): no hay nada que purgar. Si algún día se usa soft delete, agregar el job.
22. ✅ `gunicorn.conf.py`: 2 workers por defecto (`GUNICORN_WORKERS`) — regla `máquinas × workers × DB_POOL_MAX ≤ 12`.

### FASE 4 — Backend y seguridad
23. ✅ Hora argentina con `utils.ARGENTINA` / `hoy_argentina()` (Argentina no tiene horario de verano; hay un test que prohíbe restar horas a mano). Se puede cambiar `ARGENTINA` a `ZoneInfo("America/Argentina/Buenos_Aires")` si se instala `tzdata` en Windows/Docker (verificar `requirements.txt`): hoy `timezone(timedelta(hours=-3))` es equivalente.
24. ✅ La racha y «más usado» solo se marcan hechos si salieron bien (reintento a los 5 min).
25. ✅ Código de referido verificado y reintento sin quemar el email real.
26. ◐ Webhooks de MeLi: `/notificaciones_meli` y `/webhook` YA validan `application_id` contra `MELI_CLIENT_ID` y no usan el contenido como dato. Revisar si falta algo más (MeLi no firma las notificaciones; evaluar lista de IP de origen documentada por MeLi) y dejar una prueba de que un `application_id` ajeno no dispara nada.
27. ⏳ **`state` de OAuth contra cookie**: ver `auth/oauth_meli.py`, `/conectar`, `/conectar_otra_cuenta`, `/callback` y `oauth_vinculaciones_pendientes`. Guardar un valor aleatorio en la cookie de sesión firmada (HttpOnly/SameSite=Lax) al iniciar y compararlo (comparación en tiempo constante) con el `state` al volver, además de lo que ya persiste en la base. Probar el caso «state válido en la base pero cookie distinta» → rechazo.

### FASE 5 — UI/UX
28. ✅ Ganancia Real: el primario es «Descargar PDF» debajo del número; «Ver período» y el aviso informativo pasaron a secundarios.
29. ✅ Dashboard: `#hero-acciones` (sin costo → /costos, pérdida → /metricas, bien → «Ver el detalle»).
30. ✅ La pastilla de «Solo los que puedo editar» es gris (`ux-neutral ux-pill-suave`).
31. ❌ `.despacho-check` ya tiene borde naranja (`ux.css` pisa a `style.css`).
32. ❌ (decisión, reabrible) Los 6 `<details>` de `/metricas` cerrados son una línea cada uno y son la regla «detalle plegado»; no se pasaron a pestañas. Si Diego los quiere igual: pestañas `.subnav-tabs` internas, ojo con el `open` automático de reclamos, la impresión (`beforeprint` abre todo) y los gráficos que se arman al abrir.
33. ❌ El estado vacío de Despacho ya tiene su botón primario («Traer ventas nuevas») arriba.

### FASE 6 — Frontend
34. ✅ `destroy()` de los gráficos del Dashboard que se rearman.
35. ✅ Stock masivo envía solo los campos cambiados (`soloLoQueCambio`, también el par `orig_`).
36. ◐ `id_variante` viaja siempre como texto (`or ''`): `ventas.id_variante` no tiene NULL en la base (el vacío normal es `''`).
37. ✅ Gráficos de Ganancia Real con `ResizeObserver` (`_cuandoTengaTamano`); verificado en el navegador con el panel sin tamaño.
38. ◐ **Despachador `data-click` / `data-change` / `data-input` / `data-keyup` en `static/js/ux.js`** (la auditoría decía `data-action`). Migradas: `_ux.html`, Ganancia Real, Stock masivo, Despacho, Dashboard. **Faltan ~143 manejadores inline** (tope en `tests/test_correcciones_frontend.py::PRESUPUESTO_INLINE`: solo baja): `base.html` (33: menú, modales, chat, feedback), `tendencias` 12, `index` 10, `costos` 7, `precios` 6, `embudo_conversion` 5, `promociones` 4, `suscripcion` 3, `publicidad`, `onboarding`, `conectar_otra_cuenta`, `admin_panel` 2 c/u, y varias de 1; más 19 strings armados en `static/js/global.js`. Luego: ~42 `<script>` inline → nonce por pedido, probar con `Content-Security-Policy-Report-Only`, recién después sacar `'unsafe-inline'` del `script-src` (activar el nonce antes de migrar todo rompe la app). `style-src 'unsafe-inline'` se queda. Estrategia completa en CLAUDE.md.
39. ❌ Las tablas de Ganancia Real ya están dentro de `.panel` / `.ux-detalle-cuerpo` con `overflow-x: auto` (medido a 375 px: sin scroll de página).
40. ✅ Margen con facturado 0 y neto negativo = pérdida.
41. ✅ Acordeón de Stock masivo: `role="button"`, `tabindex`, `aria-expanded`, Enter/espacio (y se arregló un doble toggle por teclado del checklist del Dashboard).
42. ✅ Promesas compartidas del Dashboard que no guardan el error (`_compartida`).
43. ◐ Selector muerto del modo foco eliminado (el form ya se escondía por `.ux-periodo`).
44. ✅ Tooltips de Chart.js con los colores del tema (`_tooltip()`).
45. ✅ `.chat-window` se ajusta al ancho del celular (`shell.css`, ≤ 900 px) y se apoya sobre su botón.
46. ⏳ Múltiples botones primarios: en `templates/monotributo.html` (filtro de fechas Y acordeón). Dejar UNO. Revisar de paso TODAS las pantallas: contar `.btn-primary` visibles por pantalla (cuidado: los banners de `_ux.html` tienen `btn-primary` por defecto).
47. ✅ `ES_HOY` y la cuenta regresiva en hora de Argentina (`ahoraArgentina()`).
48. ⏳ Contraste WCAG de placeholders y estados `:disabled` (`style.css`/`ux.css`): definir color explícito, ≥ 4,5:1 en los dos temas (comprobar con tokens `--text-faint` y el tema claro).
49. ⏳ Pestañas superiores (`.subnav-tabs`, `shell.css`) cortadas: aviso de que se pueden deslizar (sombra/degradado en el borde cuando hay desborde; en celular y escritorio angosto).
50. ⏳ Animación infinita de `.ux-danger`: limitarla a la campana de arriba o al primer ítem urgente; respetar `prefers-reduced-motion`. Buscar `animation: … infinite` en `ux.css`/`style.css`.
51. ◐ z-index: `#toast-container` ahora es 9999 y `.command-overlay` 8700 (el menú móvil es 8600, su overlay 8590). Falta VERIFICAR en el navegador a 375 px con el menú abierto que el toast se vea por encima.
52. ✅ Carpeta `deploy/` borrada (sigue en el historial de git).

## 1b. EXTENSIÓN DE LA AUDITORÍA: puntos 53–78 (pegados por Diego el 2026-10-07, después de los 52) — TODOS ⏳, sin verificar ni tocar
Mismo criterio: verificar cada afirmación antes de aplicar (varias suenan mal planteadas: marcadas con ⚠️ «ojo» según lo que ya se sabe del proyecto). Los puntos 59–78 llegaron sin número: se numeraron en el orden en que vinieron.

### Frontend / operación (53–58)
53. ⏳ `/healthz/db` pega a la base en cada llamada (UptimeRobot u otro): sin caché ni tope propio puede comerse el pooler (15 conexiones de sesión para TODO el proyecto). Cachear el resultado 15–30 s en memoria del proceso (no hay datos de cuentas: no hay riesgo de mezclar tenants) y/o un tope en `limitador.py` para esa ruta; ver `seguridad.healthz_db`. Probar que N pedidos seguidos hacen 1 sola consulta.
54. ⏳ **PDF mutilado**: en Ganancia Real el botón usa `window.print()` pero las filas con `.oculto-mostrar-mas` (display:none) no se imprimen: el historial sale cortado en la fila 10 (y «Qué modelos dejan plata» en la 5). Agregar en `@media print` (`style.css`, bloque ~l.1108) `.oculto-mostrar-mas { display: table-row !important; }` (y para listas no tabla) y esconder los botones «Ver más». Ya existe `beforeprint` en `ux.js` que abre los `<details>`. Verificar imprimiendo de verdad (vista previa de impresión) y con una prueba que lea el CSS.
55. ⏳ Dashboard: el relleno del gráfico de tendencia usa `rgba(139, 92, 246, …)` fijo (`createLinearGradient` en `dashboard_personalizable.html`, widget `tendencia_ventas`); derivarlo de `--accent-primary` (helper que convierta hex→rgba o `color-mix`). Buscar otros rgba violeta fijos en JS (p. ej. burbujas de `metricas.html`: `rgba(139, 92, 246, 0.45)`).
56. ⏳ Gráficos y cambio de tema en vivo: Chart.js no se entera de `data-theme`. `MutationObserver` sobre `<html data-theme>` que rearme/actualice TODAS las instancias (guardarlas: hoy el Dashboard tiene `_graficos`, Ganancia Real no guarda ninguna; unificar en un registro global `window._charts` o un helper en `ux.js`), recalculando colores de ejes, grillas y tooltips (`_tooltip()` / `_estiloGrafico()` de `metricas.html`).
57. ⏳ Stock masivo: al borrar la búsqueda quedan abiertos los acordeones que se abrieron por buscar (`filtrarAcordeon` solo abre). Recordar el estado previo de cada ítem antes de la primera búsqueda y restaurarlo al vaciar el campo (o colapsar los que abrió la búsqueda).
58. ⏳ ◐ `beforeunload` de Stock masivo: puede estorbar a redirecciones propias del sistema (reconectar / fin de prueba). Ojo: un redirect HTTP 302 del servidor no dispara `beforeunload` de la página actual hasta que se navega; el problema real es una navegación disparada por JS. Alternativa más limpia que una bandera `window._bypassUnload`: que los `location.href` internos (sesión vencida, `/reconectar`) pasen por un helper que apague el aviso. Verificar en el navegador antes de tocar.

### Backend / base / concurrencia (59–78)
59. ⏳ ⚠️ RLS con `SELECT id FROM cuentas_meli WHERE usuario_id = …` «por fila»: medir con `EXPLAIN (ANALYZE)` en la base real; una subconsulta NO correlacionada suele evaluarse UNA vez (InitPlan), no por fila. Parente del punto 16. Si el costo fuera real, la salida es un setting plano `app.cuenta_id` por conexión (`db.conexion_usuario`) con `tests/test_rls_cuenta_activa.py` y `tests/test_aislamiento_codigo` en verde; no cambiar políticas sin probar el aislamiento entre cuentas de un mismo usuario Elite.
60. ⏳ ⚠️ `pg_try_advisory_lock` del scheduler (`scheduler.py`, un solo proceso ejecuta los trabajos): ver cómo se toma. Un lock de sesión es JUSTAMENTE lo que hace falta para la elección de líder si se sostiene en una conexión dedicada; `pg_try_advisory_xact_lock` se soltaría al terminar la transacción y rompería la exclusión. Verificar que el lock no se devuelva al pooler sin unlock (si hoy se toma y se suelta en la misma conexión del pool, ahí sí hay riesgo).
61. ⏳ ⚠️ `gevent.monkey.patch_all()`: comprobar cómo arranca Fly (`Dockerfile` CMD / `gunicorn.conf.py`: ¿`worker_class = gevent`?). El worker de gunicorn gevent parchea al cargarse; si no se usa gevent o `app.py` se importa antes del parche, hay que arreglarlo. Verificar también que psycopg3 coopere con gevent (no asumir) con una prueba de concurrencia real (consultas lentas en paralelo).
62. ⏳ ⚠️ «Flask no soporta rotación de claves»: Flask 3.1 sí (`SECRET_KEY_FALLBACKS`; CLAUDE.md dice que `FLASK_SECRET_KEY_ANTERIOR` se mapea a eso). Comprobar la versión instalada y escribir una prueba: una cookie firmada con la clave vieja debe aceptarse tras rotar. Si pasa, rechazado con evidencia.
63. ⏳ Dashboard y todo `innerHTML` armado con strings: auditar TODAS las plantillas y `static/js/*.js` buscando datos externos (títulos, apodos, nombres, mensajes de MeLi) sin `UX.esc`/autoescape. Escribir un test de guarda (regex sobre `${…}` dentro de `innerHTML` que no pasen por `UX.esc`/`esc`) o revisar a mano y dejar la lista. Los widgets del Dashboard que se vieron escapan todo.
64. ⏳ ⚠️ `_en_segundo_plano` con `threading.Thread` vs `gevent.spawn`: con el worker gevent y `monkey.patch_all()` los `threading.Thread` ya son greenlets. Verificar (punto 61) antes de cambiar; si no hay parche, usar `gevent.spawn` cuando esté disponible y caer a hilo en desarrollo/tests.
65. ⏳ `session["mas_usado"]` (auth/middleware.py `_calcular_mas_usado_sesion`) viaja en la cookie firmada en cada pedido: medir el tamaño real del `Set-Cookie`; si pesa, guardarlo en `cache_db` por usuario y dejar en la sesión solo una versión/fecha, o recalcular cada tanto. Cuidado con el límite de 4 KB de las cookies.
66. ⏳ Códigos de referido de la migración 0004 = `MD5(id::text || 'corelux_ref_v1')`: deterministas y adivinables si se conoce el id. Ver qué genera hoy `registro._generar_referral_code` (debería ser aleatorio y único). Para los usuarios existentes: valorar regenerar con `secrets` en una migración (OJO: los códigos ya compartidos dejarían de servir; Referidos está oculto en modo beta sin `MP_ACCESS_TOKEN`).
67. ⏳ ⚠️ `token_manager`/`db.conexion_admin()` ante excepciones: verificar en `db.py` que el `contextmanager` haga rollback y devuelva la conexión al pool siempre (si usa `with pool.connection()` ya lo hace). Escribir una prueba que levante una excepción dentro del `with` y compruebe que el pool recupera la conexión.
68. ⏳ `utils.extraer_talle`: ya prioriza atributo de la variación → atributo `SIZE` del ítem → título. Revisar si falta `FASHION_SIZE` y la Grilla Universal (`SIZE_GRID_ID` / `SIZE_GRID_ROW_ID`) en `sincronizador.py` (qué atributos guarda en `productos_variantes.talle`) y mirar una respuesta real de MeLi antes de agregar nada. No volver a agregar regex de talle nuevos.
69. ⏳ CSS: botones deshabilitados con `pointer-events: none` impiden ver el `title` nativo con el motivo (p. ej. zonas Flex sin precio, «Solo los que puedo editar»). Cambiar por `cursor: not-allowed` (el atributo `disabled` ya frena los clics) y verificar que ningún estilo `.disabled` dependa de eso (hay enlaces `a.btn.disabled`: ahí sí hace falta frenar el clic con `aria-disabled` y JS).
70. ⏳ Ctrl+K (`.command-overlay`, `inicializarComando` en `global.js`): agregar trampa de foco (Tab/Shift+Tab ciclan dentro), `role="dialog"` + `aria-modal="true"`, devolver el foco a quien lo abrió y cerrar con Esc. Revisar con el mismo criterio `modal-confirmar` y el modal de feedback / menú lateral.
71. ⏳ `filter: invert(0.75)` sobre el ícono nativo de `input[type="date"]` (`style.css`): en Safari iOS con modo oscuro puede desaparecer. Probar con `color-scheme: dark` / `light` por tema (el ícono nativo ya se adapta) y quitar el `filter`.
72. ⏳ ⚠️ No verificable en vivo: `/reviews/item/{id}` para productos de catálogo (la cuenta de prueba no tiene catálogo). CLAUDE.md: las opiniones se comparten por `family_id` y se consulta UNA por familia. Buscar en la documentación de MeLi si hay agrupación por `catalog_product_id` y qué devuelve para catálogo; manejar «respuesta vacía» como «sin dato», no como «0 opiniones».
73. ⏳ SIRTAC/IIBB a fin de quincena como cargo general (no ligado a una orden): hoy `retenciones` (cargos tipo `tax` del pago) se muestran APARTE y NO restan de la ganancia (pago anticipado de impuestos); la conciliación contra el depósito real dio 0,31 %. Verificar con la factura/ movimientos reales si existen débitos de recaudación fuera del pago y, si es el caso, mostrarlos como línea aparte (nunca restarlos de la ganancia diaria sin decirlo; implicancia fiscal: avisar y sugerir un contador).
74. ⏳ Migración 0026: `retirar_ventas_canceladas` borra de `ventas` (y archiva la fila completa en `ventas_retiradas`, reversible) las órdenes canceladas/reembolsadas. Verificar el caso «devolución en tránsito con la plata retenida»: la orden queda `in_mediation`/no `cancelled` mientras el reclamo está abierto y `devoluciones_sync._actualizar_dinero_retenido` suma el pago retenido. Confirmar con datos reales que no se pierde esa trazabilidad (Cobros / «dinero retenido») y que «Ventas reembolsadas» la muestra.
75. ⏳ ⚠️ Migración 0028 (`financing_add_on_fee`): CLAUDE.md ya documenta que se cobra por publicación como % casi fijo del precio y se verificó contra 100 % de ventas en 1 cuota. El caso «carrito con ítems de varios vendedores y prorrateo no lineal» no se puede comprobar sin una venta así: dejar anotado como límite conocido y revisar si hay ventas con `pack_id` compartido entre vendedores.
76. ⏳ Stock FULL: `available_quantity` ya descuenta reservas transitorias (carritos sin pagar). Revisar `full_stock.py`, la campana de avisos (`dashboard.armar_avisos`: «publicaciones activas sin stock») y el Stock: un 0 momentáneo no debería gritar «quiebre». Mirar los campos reales de `/inventories/{id}/stock/fulfillment` (`available_quantity`, `not_available_quantity`, `total`) y decidir con una respuesta real.
77. ⏳ ⚠️ Cachés en memoria globales: es la clase de bug nº 1 de CLAUDE.md y ya hay un test de guarda («caché»). Volver a barrer con grep módulos con `dict`/`list` a nivel de módulo que guarden datos de cuentas (`_cache_*`, `_ultimo_*`) y confirmar que el test los cubre; preferir `cache_db`.
78. ⏳ ⚠️ `toggleAcordeon` cambiando `display` (Stock masivo): con ~137 inputs la repintada es mínima; medirlo en un celular real antes de optimizar (alternativas: atributo `hidden`, `content-visibility: auto`, o armar el cuerpo del acordeón recién al abrir). Probablemente baja prioridad.

## 2. Resumen que hay que dárselo a Diego (frontend, 19 puntos de la 2.ª auditoría)
Corregido: botón primario de Ganancia Real; hero del Dashboard con salida; pastilla gris en Stock masivo; `destroy()` de gráficos; solo viajan los campos cambiados; hora de Argentina en Despacho; ids siempre como texto; `ResizeObserver` en gráficos; margen negativo con facturado 0; acordeón accesible; promesas que no se envenenan; tooltips por tema; ventana del asistente en celular; selector muerto fuera; doble toggle del checklist por teclado (hallazgo propio).
Primera parte de `data-click` (5 plantillas migradas + tope que solo baja + estrategia de CSP). Rechazados con evidencia: 4, 5, 9, 13. Parciales: 12, 17, 19.

## 3. Pendientes anteriores (de sesiones previas)
- Ordenar el resto de las tablas con `data-ordenable` (ya: Stock, Ganancia Real, Calidad; ver `static/js/tablas.js`).
- Ficha única de publicación (ítem 219 de `PLAN_MEJORAS.md`; el plan tiene 243 ítems: revisar cuáles quedan).
- Sacar los `onclick` para quitar `'unsafe-inline'` (ver 38).
- Mails/notificaciones (falta definir proveedor de mail; hoy solo la campana de avisos).
- Revisar de punta a punta el flujo Multi-cuenta Elite (`/conectar_otra_cuenta`) con una cuenta real (se armó por trazado de código, nunca contra Supabase en vivo).
- Flex: reconciliar contra MargenFull ($378.250 vs $326.110 para 09/09–01/10) y el caso de productos < $33.000 (paga el comprador).
- Recheck de la tabla de Monotributo de AFIP/ARCA (se ajusta ~2 veces por año; vigente desde 01/08/2026).
- Cuentas de cortesía (los 2 usuarios de la familia, Plan Elite gratis): excluirlas de cualquier cobro real el día que se implemente Mercado Pago.
- Cobro por Mercado Pago, puente de WhatsApp, inteligencia competitiva multi-mercado: no existen todavía.

## 4. Pendientes que son del DUEÑO (no se pueden hacer desde el código)
- `RESPALDO_CLAVE` y una tarea semanal de `respaldo.py` (ver `docs/RUNBOOK.md`).
- Monitor de uptime sobre `https://corelux.app/healthz`.
- Panel de MeLi Developers: tildar los temas de notificaciones y poner la Notification URL (necesario ANTES de bajar el cron, punto 14).
- Certificado de ARCA para consultar la condición fiscal (padrón/constancia de inscripción) y, mientras tanto, cargar la condición fiscal de cada cuenta en «Mi cuenta» (hoy nunca se supone).
- `MP_ACCESS_TOKEN` + `MP_WEBHOOK_SECRET` cuando se active el cobro; revisión legal de `/terminos` y `/privacidad`.
- Mirar los logs de Fly tras cada deploy buscando `invalid_grant` o `EMAXCONNSESSION`.

## 5. Trampas conocidas de este entorno (para no repetirlas)
- Desplegar SIEMPRE con `python desplegar.py` desde `CoreLux-SaaS` (en segundo plano) y NO editar archivos mientras construye la imagen.
- El servidor de vista previa local usa la base de PRODUCCIÓN: nunca enviar formularios ni hacer POST reales al probar (stub de `fetch`). Borrar `static/_prev` antes de commitear/desplegar.
- Heredocs de bash con comillas/backticks se corrompen: escribir con Write y correr el script; en Windows usar `MSYS_NO_PATHCONV=1`.
- `scroll`/`requestAnimationFrame` no son confiables con el panel del navegador en segundo plano (`document.hidden`, `innerWidth` 0): para medir layout, traer la pestaña al frente y fijar el tamaño.
- El `.env` local no sirve para refrescar tokens de MeLi (`invalid_client`).

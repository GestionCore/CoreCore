# CoreLux — contexto de traspaso para Claude Code

> ⚠️ **LEER PRIMERO: [`PENDIENTES.md`](PENDIENTES.md)** — lista viva de lo que falta: los 52 puntos de la 3.ª auditoría externa + la extensión de los puntos 53–78 (Fase 1 «Integración con Mercado Libre» es la que sigue, fase por fase), el estado de cada uno
> (✅ hecho / ❌ rechazado con evidencia / ⏳ pendiente), lo que quedó de sesiones anteriores y lo que es del dueño. Regla: verificar cada punto de una auditoría contra código/base/navegador antes de tocarlo (~25 % son falsos).

Sos la continuación de un proyecto largo. Todos los archivos del código
ya están subidos al contexto — este mensaje es la parte que NO se ve
leyendo el código: decisiones, motivos, y bugs ya resueltos que no se
deben reintroducir sin querer.

## Qué es esto
CoreLux es la versión SaaS multi-tenant de "Santi Mens", una app Flask
de gestión para un negocio de indumentaria en Mercado Libre (Argentina).
El objetivo es venderla como suscripción a otros vendedores de MeLi
($40.000 ARS/mes plan base, $99.000 plan elite, prueba de 14 días).
La carpeta del proyecto original single-tenant (SQLite) sigue existiendo
aparte y NO se toca — CoreLux vive en su propia carpeta `CoreLux-SaaS`.

## Stack real (no asumas lo típico)
- Flask + **PostgreSQL/Supabase** (no SQLite)
- **psycopg 3** (`psycopg[binary,pool]`), NO psycopg2 — se migró a mitad
  de proyecto porque el usuario tiene Python 3.14 y psycopg2-binary no
  tiene wheel precompilado para esa versión. Mismo motivo por el que
  Pillow tiene que ser `>=12.0.0`.
- Multi-tenant real con **Row Level Security** de Postgres — no es un
  filtro `WHERE cuenta_id = X` a mano, es una política de RLS que lee
  `current_setting('app.usuario_actual')`.
- El usuario corre todo dentro de un **venv** (`venv\Scripts\activate.bat`
  en Windows) — su Python del sistema/Microsoft Store NO tiene nada
  instalado, no asumas que un `pip install` global sirve.

## Los dos canales de conexión a la base — no los mezcles
- `db.conexion_usuario(usuario_id)`: uso normal, con RLS activo. Usa
  `SELECT set_config('app.usuario_actual', %s, true)` — el `true` (no
  `false`) es intencional: hace que la variable dure toda la
  TRANSACCIÓN, no la sesión completa, porque el pooler de Supabase en
  modo transacción no preserva variables de sesión de forma confiable
  entre instrucciones. Encontrarlo costó un bug real en producción.
- `db.conexion_admin()`: bypassea RLS. USAR SOLO en `token_manager.py`
  — la tabla `meli_tokens` bloquea TODO acceso desde el rol normal a
  propósito, ni el propio usuario puede leer sus tokens crudos.
- El pool es `ConnectionPool` de `psycopg_pool` (no `SimpleConnectionPool`
  de psycopg2, que no es segura para multi-hilo). Flask corre con
  `threaded=True`.

## Reglas de negocio que NUNCA se rompen
- Ganancia Neta Real = Facturación − Cargos MeLi − Envíos − Publicidad
  − Costo de Fabricación.
- Los consolidados por modelo (agrupando talles) usan SIEMPRE promedio
  ponderado real (Total $ / Unidades) — nunca promedio simple de talles.
- FULL es de solo lectura de stock (no se puede editar desde acá).
- Confirmación explícita antes de cualquier acción que modifique datos
  reales o toque plata.

## Los ~12 bugs reales ya encontrados y corregidos (misma familia)
Casi todos son la misma clase de error: **estado en memoria compartido
entre TODAS las cuentas en vez de aislado por cuenta** — invisible con
un solo usuario, real en cuanto hay dos:
1. `ads.py` — caché de advertiser_id por site_id solo, no por cuenta
2. `facturacion.py` — dos cachés de alcance global/sesión
3. `logistica.py` — caché de Flex en un único slot global
4. `tendencias.py` — caché de categoría en un único slot global
5-6. `embudo_conversion.py` — dos cachés más, mismo patrón
7. `sincronizador.py` — el lock de sincronización era uno solo para
   TODO el proceso (ahora es un lock por cuenta_id)
8. El esquema original solo tenía política de RLS en 3 de 21 tablas —
   el resto quedaba con RLS activado SIN política = bloqueaba todo
9. Faltaba `import jsonify` de Flask en `app.py` — rompía 19 endpoints
   JSON en silencio hasta que se probaba alguno puntual
10. Faltaba también `import requests` a nivel de módulo
11. El scheduler periódico sincronizaba una sola cuenta hardcodeada
12. `set_config(..., false)` en vez de `true` (ver arriba)

Moraleja: cualquier variable/diccionario a nivel de módulo que guarde
algo "para no repetir la consulta" es sospechoso — preguntate si está
scopeado por cuenta_id antes de confiar en él.

## Arquitectura de sincronización
- `sincronizador.py`: catálogo (productos_padre/variantes) desde la API
  de MeLi.
- `ventas_sync.py`: ÓRDENES reales desde `/orders/search` — este módulo
  NO EXISTÍA durante buena parte del proyecto; su ausencia fue la causa
  raíz de "no aparecen ventas". Es incremental: guarda
  `cuentas_meli.ultima_sincronizacion_ventas` y arranca desde ahí la
  próxima vez, con 2hs de colchón hacia atrás.
- `sincronizador.sincronizar_todo(usuario_id, cuenta_id)` orquesta las
  dos y marca `sincronizacion_inicial_completa = true` al terminar.
- Se dispara solo, en un hilo de fondo, apenas alguien conecta su
  cuenta (dentro de `/callback`).
- `scheduler.py` corre esto cada 4 minutos, para TODAS las cuentas
  activas (no una hardcodeada).

## Onboarding + tutorial (ya construido)
- Cuenta nueva → `/onboarding` (3 preguntas: prioridad_principal,
  experiencia_meli, pantalla_preferida) ANTES de cualquier otra cosa.
- `auth/middleware.py`'s `login_requerido` chequea, en este orden:
  onboarding completo → sincronización inicial completa → recién ahí
  deja pasar a la vista real.
- `/` respeta `pantalla_preferida` (no siempre manda a Stock).
- Tutorial guiado con blur/spotlight sobre el nav, disparado una sola
  vez vía flag de sesión `mostrar_tutorial`, apagado por
  `/onboarding/tutorial_visto`.

## Lo más nuevo (última sesión)
- **Monotributo** (`monotributo.py`, `/monotributo`): compara
  facturación real de 12 meses contra las escalas de AFIP. Tabla
  vigente **desde el 1/08/2026** — ATENCIÓN: AFIP ajusta esto ~2 veces
  por año, hay que rechequear los montos periódicamente, no son fijos.
  La proyección de si va a cruzar de categoría usa el ritmo de venta
  PROPIO del usuario, no predicción de demanda de mercado externo (eso
  es un feature más grande, ver más abajo).
- **Costos por chat** (`costos_chat.py`, `/api/costos_chat`): IA
  convierte una descripción en lenguaje natural en un gasto
  estructurado, pregunta el período si falta, y SIEMPRE pide
  confirmación explícita antes de guardar — nunca escribe directo.
  `gastos_operativos` ahora soporta `recurrente` + `fecha_fin`, con
  prorrateo por día en `costos.py` cuando el período elegido es más
  corto que un mes. También carga **costo de fabricación por grupo de
  productos** ("las camperas de jean valen 12000"): la IA solo extrae
  grupo + monto; quién es el grupo lo resuelve
  `resolver_grupos_de_productos` SIN IA (todas las palabras del grupo
  en el título, singularizadas; el grupo más específico se queda con
  la publicación), y la confirmación muestra cada modelo afectado con su
  costo de antes. Confirmar guarda solo los ids que el usuario vio, bajo RLS.
- **Multi-cuenta real (Plan Elite)**: `/conectar_otra_cuenta` vincula
  una segunda cuenta de MeLi al usuario YA logueado (en vez de crear un
  usuario nuevo, que es lo que hacía `/conectar` siempre) —
  `registro.vincular_cuenta_adicional()`, gateado a `plan == 'elite'`
  server-side. El selector del nav (`cuentas_disponibles` /
  `/cambiar_cuenta`) ya existía en el código pero estaba huérfano —
  ahora sí tiene un flujo real que lo alimenta. Antes de construir esto
  se auditó a fondo si el aislamiento entre cuentas de un mismo usuario
  era seguro (la preocupación real: que todas las pantallas de
  análisis mostraran datos MEZCLADOS de las 2 cuentas) — se confirmó
  que las 58 rutas de `app.py` que abren conexión con RLS pasan
  `g.cuenta_id` siempre, así que la migración 0010 (RLS por cuenta
  activa) ya protege de verdad, no solo en el papel. El comentario
  viejo de advertencia en `auth/registro.py` sobre esto estaba
  desactualizado y se corrigió.
  ⚠️ Esto se armó por trazado de código contra el patrón ya probado
  (`crear_o_actualizar_login`), pero NUNCA se corrió contra Supabase
  real en vivo — el sandbox donde se escribió no tiene salida de red a
  Postgres (solo HTTPS). Antes de confiar en esto a ciegas con más
  usuarios, probarlo de punta a punta con una cuenta real.
- **Cuentas de cortesía**: las 2 cuentas de MeLi de la familia del
  dueño (sus padres) están en Plan Elite gratis, seteado a mano por
  `UPDATE usuarios SET plan = 'elite'` — nunca pasaron por Mercado
  Pago. El día que se implemente cobro real, ASEGURARSE de excluir
  estos `usuario_id` de cualquier proceso de facturación — no tienen
  (ni van a tener) una suscripción real de MP detrás.
- **Entrega Flex** (`flex.py`, `flex_zonas.py`, migraciones 0018–0021): en
  Flex el vendedor entrega con su propia logística y MeLi reporta
  `costo_envio = 0`; el costo real lo cobra esa logística por zona. Las zonas
  las define MeLi, NO el usuario: `GET /flex/sites/MLA/users/{id}/subscriptions/v1`
  (OJO: sin `/shipping/` — con esa ruta MeLi da 404 siempre; `logistica.py`
  tenía ese bug y decía "no tenés Flex") trae el domicilio de salida y
  `.../services/{service_id}/configurations/coverage/zones/v1` las zonas de
  cobertura (45 en AMBA: partidos + CABA + algunas especiales). El envío NO
  trae su zona, solo localidad/CP/coordenadas: `flex_zonas.py` ubica cada
  destino en una zona (Capital Federal → CABA; lista de localidades por
  partido; si no, el centro de zona más cercano ≤ 9 km). El usuario carga
  "umbrales" (precio + zonas que cubre) en Costos, como en MargenFull; lo que
  no mueve cae en el umbral "resto" (siempre existe). Guardado en
  `cuentas_meli.flex_umbrales` / `flex_info`. MeLi reintegra el 10% del
  envío (`REINTEGRO_MELI`): el costo que se descuenta es precio × 0.9, y la
  pantalla lo explica. `ventas.costo_envio` = lo que informa MeLi +
  `ventas.costo_flex`, así Ganancia Real/Dashboard/Facturación/Fiscal lo suman
  sin tocar sus cálculos; `ventas_sync` conserva `costo_flex` al reprocesar y
  TODA asignación mueve `costo_flex` y `costo_envio` juntos (`flex._aplicar`,
  una sentencia para cualquier cantidad de órdenes). `ventas.flex_zona` = id
  del umbral (0 = sin costo, NULL = pendiente), `flex_zona_meli` = zona donde
  se ubicó ('*manual' si el usuario eligió a mano: el recálculo no lo toca).
  El sync aplica solo a los envíos nuevos y refresca las zonas 1 vez por
  semana; guardar umbrales NO toca ventas: muestra una vista previa
  (envíos y costo por umbral) y el usuario confirma. Una venta ya valuada
  queda con su precio salvo que el usuario tilde "incluir ya valuadas".
  `ventas_sync._completar_datos_de_envio` completa de a 40 por pasada tipo de
  logística y destino de ventas viejas (60 días).
  ⚠️ Pendiente de contrastar con el usuario: para 09/09–01/10 MargenFull
  muestra $378.250 de costo Flex y esta lógica da $326.110 bruto (39 envíos);
  no se pudo reconciliar. Tampoco se modeló el caso de productos < $33.000
  (ahí paga el comprador): el vendedor de prueba no tiene ventas Flex así.

- **Lo que MeLi realmente cobra (migraciones 0022–0023, 2026-10-01)**: se
  verificó contra el depósito real (`GET /collections/{payment_id}` →
  `net_received_amount`; `https://api.mercadopago.com/v1/payments/{id}` →
  `charges_details` con cada cargo y su dirección). `ventas.costo_envio` NO es
  `shipping_option.cost` (eso lo paga el comprador, 0 si es gratis): es el
  costo real del vendedor, `GET /shipments/{id}/costs` → `senders[0].cost`
  (FULL ≈ 15% de la venta), repartido entre todas las filas que comparten
  envío (`envio_shipment_total` → `costo_envio_meli`, `_repartir_envios`; los
  packs comparten un envío) + `costo_flex`. Flex: MeLi no cobra envío (0).
  `costo_envio_original` conserva el valor viejo de cada fila corregida.
  `cargo_venta` = comisión + financiación (`sale_fee`) + cupones que financia
  el vendedor (`coupon_fee`, de collector a ml; los cupones de MeLi al
  comprador no cuestan nada). `retenciones` (cargos de tipo `tax`: IIBB,
  SIRTAC) se muestran APARTE y NO restan de la ganancia (son pago anticipado
  de impuestos). `neto_recibido`, `fecha_liberacion`, `monto_liberacion`
  (antes nunca se llenaban: el ticker "Disponible mañana" era siempre $0) salen
  del pago. Con todo esto el cálculo coincide con el depósito real al 0,31%
  (1.062 ventas, $56,6 M; Flex 0,00%). Ganancia Real muestra la conciliación.
  El relleno de ventas viejas es gradual (`_completar_datos_de_envio` /
  `_completar_datos_de_pago`, 540 días). Antes de esto la ganancia salía ~12-15%
  de la facturación por encima de la real.
- **Capacidades por cuenta** (`capacidades.py`, `cuentas_meli.capacidades`):
  CoreLux lo usan vendedores de TODOS los rubros, no solo indumentaria ni solo
  el dueño. Cada cuenta tiene `ads / flex / full / catalogo` en True/False/
  ausente; solo un False confirmado esconde una pantalla o sección (ausente
  nunca esconde). Disponible en templates como `capacidades`. No escribir
  textos ni lógica específicos de un rubro (talles, indumentaria) ni de una
  región: Flex hoy ubica destinos solo en AMBA (`flex_zonas.py`), el resto cae
  en "resto de las zonas".
- **Enriquecimiento de publicaciones** (`enriquecimiento.py`): de a un lote
  chico por sync completa en `productos_padre` calidad (`/item/{id}/performance`,
  con el link directo para resolver cada acción), visitas 14d vs 14d previos
  (`/items/{id}/visits/time_window`), stock no disponible en FULL
  (`/inventories/{id}/stock/fulfillment`) y precio para ganar el catálogo
  (`/items/{id}/price_to_win`, solo publicaciones de catálogo). Las pantallas
  leen de la base, nunca esperan a la API.
- ⚠️ **Bug de producción corregido 2026-10-01**: MeLi limita
  `GET /items?ids=` a **20 ids**; el sync de catálogo pedía 50 → 400 en
  silencio → no se actualizaba NINGUNA publicación ("0/83 ítems
  sincronizados"; probablemente era el "no me muestra todas las publicaciones"
  de `cosas.txt`). Mientras producción corra el código viejo sigue roto.
- **Pantallas nuevas sobre datos de MeLi ya guardados** (2026-10-01), todas
  generales para cualquier rubro y ocultas si no aplican a la cuenta:
  `/calidad` (`calidad.py`: puntaje y acciones de MeLi + visitas/conversión),
  `/precios` (`precios.py`: precio mínimo = ganancia $0 y recomendado = margen
  objetivo, con la comisión (`cargo_venta`, incluye cuotas y cupones) y el envío
  POR UNIDAD reales de cada publicación en 90 días; NUNCA se estima con el
  promedio de otras publicaciones — el envío de dos productos no se parece —,
  las que no vendieron van aparte), unidades de FULL no disponibles en Stock
  (`full_stock.py`, se cuentan UNA vez por `inventory_id`: varias publicaciones
  comparten inventario), cupones financiados en Promociones
  (`promociones.obtener_cupones`), tendencia de visitas en el Embudo, límite de
  despacho por paquete en Despacho (`GET /shipments/{id}/sla` → `expected_date`
  y `status`), panel de catálogo en Competencia (`catalogo_ganar.py`: precio
  para ganar el puesto principal cruzado con el precio mínimo; ⚠️ construido
  contra la documentación, sin ver nunca una respuesta real: la cuenta de prueba
  no tiene catálogo) y aviso de mensajes de compradores sin leer
  (`mensajes.py`, `/api/mensajes/sin_leer`; ⚠️ la app NO envía mensajes: se
  responde en MeLi; el largo máximo del vendedor es 350 caracteres y las órdenes
  FULL vienen `blocked_by_fulfillment`).
- **Lo que se esconde según `capacidades`**: Publicidad (`ads`), Competencia
  (`catalogo`), panel Flex de Costos (`flex`), columna/KPI FULL de Stock
  (`full`); nav (`requiere` en `nav_config.py`), Ctrl+K (`window.CAPACIDADES`) y
  subnav. Ganancia Real muestra Flex solo si hay envíos Flex.
- **Webhooks** (`/notificaciones_meli` y `/webhook`, `sincronizador.procesar_notificacion_webhook`):
  validan `application_id` contra `MELI_CLIENT_ID`, no usan el contenido como
  dato (solo deciden QUÉ volver a pedir a MeLi) y juntan ráfagas con
  `antirrebote.py` (1 sync por cuenta cada 15 s). Temas: `items`, `orders_v2`/`orders`/
  `shipments` (sync de ventas), `questions`, `claims`/`post_purchase`.
  ⚠️ Falta, del lado del usuario, tildar esos temas y poner la Notification URL
  `https://corelux.app/notificaciones_meli` en el panel de MeLi Developers
  (no se puede hacer desde acá). Mientras tanto el scheduler (4 min) cubre todo.
- **Reclamos: solo es grave el que afecta la reputación (migración 0025)**:
  `incidencias_posventa.afecta_reputacion` guarda lo que dice MeLi
  (`GET /post-purchase/v1/claims/{id}/affects-reputation` → `affected` /
  `not_affected`; NULL = todavía no se consultó y se trata como "podría afectar").
  `utils.SQL_RECLAMO_AFECTA` es el fragmento SQL para contar solo esos: lo usan el
  ticker, Salud de cuenta (antes 4 "no lo quiero" en mediación restaban 45
  puntos), Logros, resumen semanal, Ganancia Real y Reputación. Lo que MeLi marca
  `not_affected` + las devoluciones se muestran como "por gestionar, sin impacto
  en tu reputación". `devoluciones_sync` lo refresca en cada sync de reclamos.
- **Opiniones de compradores (`/opiniones`, `opiniones.py`, migración 0027)**:
  `GET /reviews/item/{id}` da calificación, estrellas 1-5, los atributos que MeLi
  define por categoría ("al 86% le quedó como esperaba") y los comentarios; el
  filtro `rating=N` trae las de 1, 2 y 3 estrellas. Lo completa
  `enriquecimiento.refrescar_opiniones` (cada 24 h, de a 12). ⚠️ Las opiniones se
  comparten por **`family_id`** (todos los talles/variantes de un modelo): se
  consulta UNA por familia y se cuenta una vez; algunas publicaciones pausadas
  de la familia reportan 0, vale la fila con más. `user_product_id` cambia en cada
  talle, `family_id` no — es la clave de "modelo" que no depende del título ni del
  rubro (el sincronizador la guarda en `productos_padre.family_id`): usarla si
  alguna vez se reemplaza el agrupado por título.
- ⚠️ **Hora de las ventas**: Mercado Libre informa `date_created` como `…-04:00` (instante
  correcto) aunque Argentina es UTC−3. Hasta 2026-10-01 `ventas_sync` guardaba la parte local
  tal cual, 1 hora atrasada (una venta de 00:30 ART caía en el día anterior). Ahora
  `ventas_sync._fecha_hora_argentina` convierte al ingresar y marca `ventas.hora_normalizada`
  (migración 0031). Las filas viejas (false) se corrigen con `normalizar_horas.py --aplicar`
  (vista previa por defecto; APLICADO por el dueño el 2026-10-02: las 2.641 ventas están normalizadas). Para todo lo que dependa de la HORA
  (mapa de horarios, "cuándo te compran", corte de Despacho) usar
  `utils.sql_momento_argentina()`: da lo mismo para filas viejas y nuevas, así el código es
  correcto antes y después de normalizar. NO volver a sumar "+1 hora" a mano en una consulta.
  Lo que agrupa por `fecha_venta` (ventas del día) solo se corrige con el script.
- **Trabajo en segundo plano: `app._en_segundo_plano`** (Celery si hay Redis, si no
  un hilo). Producción NO tiene Redis: antes cada `.delay()` tardaba ~0,7 s en
  fallar y el webhook de MeLi (`POST /notificaciones_meli`, ya está recibiendo
  notificaciones) respondía en 771 ms; MeLi pide respuesta casi inmediata y deja de
  mandar notificaciones si falla seguido. Ahora Redis se comprueba una sola vez al
  arrancar (1-2 ms por webhook). No volver a llamar `.delay()` directo en una ruta.
- **Cobros (`/cobros`, `cobros.py`) y dinero retenido**: calendario de acreditación
  con `ventas.fecha_liberacion`/`monto_liberacion` (lo que Mercado Pago deposita de
  verdad) y la plata retenida por reclamos. `incidencias_posventa.monto_retenido`
  estaba siempre en 0: ahora `devoluciones_sync._actualizar_dinero_retenido` suma el
  pago de la orden en estado `in_mediation` mientras el reclamo sigue abierto (una
  sola vez por orden). Un reclamo que "no afecta la reputación" igual retiene la plata.
- **Facturación: los períodos del 9 al 8 son el ciclo REAL de MeLi** (se verificó con
  `GET /billing/integration/monthly/periods`: `2026-09-09 → 2026-10-08`). No es un bug.
- **Costo de ofrecer cuotas (migración 0028, `ventas.financiacion`)**: el cargo
  `financing_add_on_fee` (collector → ml) del pago. ⚠️ Se cobra **por publicación,
  como un % casi fijo del precio, en CADA venta aunque el comprador pague de
  contado** (se verificó: en publicaciones con 100% de ventas en 1 cuota —dinero
  en cuenta, débito, transferencia— el cargo igual es 8-13%). Por eso el panel de
  Ganancia Real ("Lo que te cuesta ofrecer cuotas") agrupa POR PUBLICACIÓN y no
  por cuotas elegidas por el comprador. Ya está DENTRO de `cargo_venta`: es un
  desglose, no resta nada de nuevo. Se rellena de a 30 órdenes por sync.
- **Ventas canceladas/reembolsadas después de sincronizarlas (migración 0026)**:
  el sync pide órdenes por fecha de CREACIÓN y nunca guarda las canceladas, pero
  una orden paga que se cancela días después (devolución con reembolso) seguía en
  `ventas` y sumaba a facturación y ganancia. `ventas_sync.retirar_ventas_canceladas`
  busca las canceladas que CAMBIARON desde la última sincronización
  (`order.status=cancelled` + `order.date_last_updated.from`), las borra de `ventas`
  y archiva la fila completa (JSON) en `ventas_retiradas` — reversible. Ganancia
  Real muestra "Ventas reembolsadas". No agregar filtros de cancelación en las
  ~80 consultas que leen `ventas`: la tabla ya no las contiene.
- ⚠️ **Pooler de Supabase = 15 conexiones de sesión para TODO el proyecto**
  (rol `app_backend`). Cada worker de cada máquina tiene su propio pool:
  **workers × máquinas × `DB_POOL_MAX` ≤ 12** (hoy 2 máquinas × 2 workers × 3 en
  `fly.toml`; antes eran 4 por proceso = hasta 16 → `EMAXCONNSESSION` en producción).
  Si se agregan máquinas o workers, bajar `DB_POOL_MAX`. Si localmente da
  `EMAXCONNSESSION`/`PoolTimeout`, revisar `pg_stat_activity` (`usename='app_backend'`).
- **Talle, centralizado (2026-10-01)**: `utils.extraer_talle(titulo, talle_real)` es
  la ÚNICA forma de obtener el talle (antes un regex repetido en 8 módulos que
  tomaba cualquier número del título: "Combo 2 Termos" quedó con "talle 2").
  Orden: atributo de la variación → atributo `SIZE` del ítem de MeLi (el
  sincronizador lo guarda en `productos_variantes.talle`) → título, donde solo
  vale una letra (S/M/L/XL/XXL/XXXL), "talle N" explícito o 1-2 dígitos AL FINAL
  ("… Inflable 7"); un número en el medio no es talle. `limpiar_titulo_modelo`
  usa el mismo criterio para la clave de modelo. Se verificó contra todos los
  títulos reales: 0 claves de modelo distintas y solo 3 talles cambian (los 3
  eran errores). No agregar regex de talle nuevos: llamar a `extraer_talle`.
  Los textos y prompts de IA, el calendario estacional y Tendencias tampoco asumen indumentaria.

## Lo que NO existe todavía (no asumas que sí)
- Puente de WhatsApp (Baileys) — comentado en `iniciar_corelux.bat`
- Auditoría automática de devoluciones/cancelaciones más allá de lo
  que ya cubre `ventas_sync.py` (el mapeo de motivo de reclamo sigue
  sin terminar de ajustar, ver `cosas.txt`)
- Cobro por Mercado Pago
- El Dashboard ya tiene tarjetas KPI (Design System v2), pero sigue
  siendo mayormente cuadros de resumen — más variedad real de
  gráficos (no solo el de tendencia de ventas) sigue sin hacerse
- La visión de largo plazo (inteligencia competitiva cruzando
  Amazon/Alibaba/otros mercados de Latam, predicción de tendencias,
  eventualmente otros marketplaces como Tiendanube/Shopify y redes
  sociales) — es una conversación de arquitectura aparte, todavía sin
  arrancar

## Cómo prefiere trabajar el usuario
- Probar de verdad contra Postgres real para cualquier cosa que toque
  seguridad, plata, o aislamiento entre cuentas — pero calibrar el
  esfuerzo al riesgo: un cambio de texto no necesita una batería de
  pruebas completa.
- Ser directo si algo que se construyó antes estaba mal — sin
  vueltas, pero sin exagerar tampoco.
- El texto de la app tiene que sonar profesional y seguro de sí mismo
  — evitar frases que "protestan de más" o plantan dudas (ej: evitar
  comparaciones tipo "no como otros" o "nunca hacemos X" cuando nadie
  preguntó eso).
- Para cualquier cosa con implicancia fiscal/legal (como Monotributo):
  avisar y sugerir, nunca decir "hacé esto" con total seguridad —
  siempre sugerir confirmar con un contador.
- ⚠️ **ACTUALIZADO 2026-09-30 — la identidad visual YA NO es Tron/vaporwave.**
  El usuario confirmó explícitamente el cambio de dirección (commit
  `3212a1b`, "Design System v2"): fondo grafito plano, tarjetas de
  borde casi invisible (referencia estructural Escalafy), violeta
  (`--accent-primary`, hoy `#8b5cf6`) como identidad Y color de acción
  (botones primarios, estados activos de nav), dorado (`--accent-brand`,
  ahora alias del mismo token) reservado solo para logo/badges "más
  usado"/momentos de ganancia puntual — nunca botones ni estados
  activos. El canvas de partículas (`particulas.js`) se dejó de
  incluir. Lo que SIGUE intocable es la regla en sí — no cambiar el
  look sin confirmación explícita del usuario, sea cual sea el look
  vigente en ese momento — no asumas que "Tron" es la referencia actual.
- Entregar solo los archivos que cambiaron, respetando la carpeta real
  del proyecto (no volver a comprimir todo el proyecto entero cada vez).

## UX v3 — rediseño de todas las pantallas (2026-09-30)
Plan y checklist en `PLAN_UX.md`. El usuario pidió "100% experiencia de
usuario": foco rápido, botones y frases con **negrita** sobre lo que pasa,
y color donde hay que mirar. Piezas (usarlas, no reinventar HTML):
- `static/css/ux.css` — componentes de foco. Un solo mecanismo de color:
  cada pieza lee `--ux-c` y se tiñe con una clase de estado (`ux-ok`
  verde=plata/todo bien · `ux-danger` rojo=urgente/pierde plata ·
  `ux-warn` naranja=atención · `ux-info` celeste · `ux-accion` violeta ·
  `ux-gold` logros/premium · `ux-neutral`). Clases: `ux-banner`, `ux-hero`,
  `ux-kpi(s)`, `ux-item-accion` (cola "qué hago"), `ux-pill`, `ux-detalle`
  (`<details>` plegable), `ux-vacio`, `ux-barra`, `ux-barra-accion`
  (barra fija "N cambios sin guardar"), `ux-tabla-cards` (tabla → tarjetas
  en celular), `ux-periodo` (barra de período).
- `templates/_ux.html` — macros Jinja (`banner`, `kpi`, `delta`, `vacio`,
  `seccion`) y `static/js/ux.js` — `UX.banner/kpi/accion/plata/pct/esc`
  para pantallas armadas con fetch. Filtros Jinja `|plata |pct |numero`.
- Componentes visuales agregados después (en `ux.css`, mismos tokens): `ux-medidor`
  (ROAS contra equilibrio con zonas), `ux-embudo`, `ux-rank-fila` (ranking con
  foto + barra de color por rendimiento), `ux-camp-card`, `ux-dist-fila`
  (distribución), `ux-ministats`, `ux-chip-serie` (series del gráfico que se
  prenden/apagan), `ux-donut-*`, `ux-split`. Los gráficos Chart.js leen los
  colores de los tokens (`--success`, `--danger`, `--border-soft`…) para que el
  tema claro funcione; no escribir `rgba(255,255,255,…)` fijo para grillas.
  Un gráfico dentro de un `<details>` cerrado mide 0: armarlo al abrir o sacarlo a la vista.
- Regla de las pantallas: cómo voy → qué hago → números → detalle plegado.
  Un botón primario por pantalla; el historial y las tablas largas al final.
- **Todo texto externo (MeLi, base, usuario) se escapa** (`UX.esc` / autoescape).
  `|safe` solo para HTML armado por nosotros.
- Cuidado con el costo de fabricación en $0: la "ganancia" queda inflada. Las
  pantallas lo avisan (Dashboard, Ganancia Real, Costos) y el hero no se pinta
  de verde en ese caso.
- Trampas conocidas: en Jinja `dict.items` choca con la clave `items` (usar
  otro nombre); `\b`/`\n` dentro de heredocs de bash/python se corrompen al
  editar archivos (usar Edit/Write); el tema claro necesita overrides en
  `ux.css` para lo que `style.css` deja fijo en oscuro.
- Lo que NO se tocó a propósito: backend de cálculos de plata, RLS, sync.
- **Pulido visual 2026-10-02** (pedido del dueño: "que se vea hermoso"; la identidad grafito + violeta + dorado NO cambió):
  - Cifras: `--font-data` es Inter con dígitos tabulares (Space Mono se sacó: se veía como código y cortaba los KPI). `--font-mono` solo para `kbd`.
  - Plata en pantalla SIN centavos: `utils.formatear_moneda` da pesos enteros ("1.234.568"); `|plata` igual. Los Excel usan el número crudo.
  - Fechas para personas: `|fecha` ("2 sep", con año si no es el actual), `rango_fechas(desde, hasta)` ("2 sep – 2 oct"), `utils.cuando_corto`
    ("Hoy 14:32", "Ayer 21:05"). Nunca mostrar "2026-09-02". El selector de rango (RangoFechas en global.js) usa el mismo formato.
  - Plurales: `utils.plural(n, "venta")` / `|plural`; nunca "venta(s)". `utils.corregir_plurales` arregla al mostrar textos viejos guardados.
  - Los paneles NO se levantan al pasar el mouse (solo lo clickeable: `a.panel`, `a.ux-kpi`, `.widget-dashboard`). `.panel-title` alinea a la
    izquierda y empuja al final la nota/botón (antes space-between centraba el título).
  - Cada `h1.page-title` lleva `<svg class="icon page-title-icono">` con el MISMO ícono que la página tiene en el menú.
  - Tablas: los costos van en gris (`td.num.costo`), el color queda para el resultado. Estados vacíos (`.alert-empty`) sin círculo animado.
  - Jinja: nunca `"<b>" ~ (x|e)` — con autoescape escapa también el `<b>` y se ve escrito (pasó en Logros). Un test lo impide.
  - Se sacó el botón flotante "HUD" (repetía la barra superior y tapaba contenido). La landing (`landing.html`) muestra el producto con DATOS
    DE EJEMPLO rotulados: nunca poner números reales de una cuenta ahí (es pública).
- MeLi cerró (403) `/sites/{site}/search`, el detalle de publicaciones ajenas
  (`/items/{id}`) y `/highlights`: Tendencias y Competencia se rehicieron sobre
  `/products/search`, `/products/{id}/items`, `/categories`, `/users`.

## Deploy — Fly.io, no Railway (cambiado 2026-09-29)
- Producción real: **Fly.io**, app `corecore`, región `gru` (São Paulo)
  — mismo `fly.toml` en la raíz. Railway se descartó porque no tiene
  ninguna región en Sudamérica (las 4 disponibles son California,
  Virginia, Amsterdam, Singapur) — la distancia física a Supabase
  (también São Paulo) causaba ~4s de latencia real en endpoints
  simples, confirmado con logs de producción, no especulado.
- Dominio propio: `corelux.app` (comprado en Cloudflare, DNS ahí
  también, proxied). `MELI_REDIRECT_URI` productivo:
  `https://corelux.app/callback`.
- `Dockerfile` + `.dockerignore` en la raíz — deploy es `fly deploy`,
  no gunicorn+systemd+nginx a mano (la carpeta `deploy/` de esa ruta
  vieja —systemd, nginx, Celery— se borró el 2026-10-07: sigue en el
  historial de git si alguna vez hace falta).
- Auto-deploy en el proveedor (Railway) se había dejado apagado a
  propósito para forzar correr migraciones de Supabase antes de cada
  deploy — confirmar si Fly.io tiene el mismo criterio configurado o
  si los deploys ahí son manuales/vía CLI.

## Historial de sesiones en paralelo (2026-09-30)
Mientras una sesión trabajaba en la nube (sin acceso a Postgres real
ni al navegador logueado del usuario), otra corrió en la PC local del
usuario sobre la MISMA carpeta, generando ~38 commits de divergencia
real (bugs de producción, Design System v2, multi-cuenta Elite,
migración a Fly.io) sin verse entre sí. Se reconcilió con un merge de
git real (no se descartó nada a ciegas): se guardó el trabajo local
sin commitear en la rama `respaldo-local-pre-sync` antes de tocar
nada, y en los 20 archivos con conflicto (todos templates + CSS del
Design System v2) ganó siempre la versión más nueva porque en cada
caso era una evolución estricta de la versión local, nunca contenido
único perdido. **Moraleja para la próxima vez que haya sesiones en
paralelo**: si vas a pasar a otra sesión (nube ↔ local), pusheá y
avisá ANTES de que la otra arranque a divergir mucho, o al menos
dejalo documentado en este archivo apenas pase.

## Seguridad y operación (2026-10-01, auditoría de 100 puntos: `AUDITORIA_2026-10-01.md`)
Estado de cada punto en ese archivo (✅/◐). Lo que hay que saber para no romperlo:
- `seguridad.py` (se activa con `seguridad.iniciar(app)`): anti-CSRF por `Sec-Fetch-Site`/`Origin` en todo POST/PUT/PATCH/DELETE (exentos los
  webhooks `/notificaciones_meli`, `/webhook`, `/webhook/mercadopago`), cookie HttpOnly/SameSite=Lax/Secure en Fly, cabeceras, `/healthz` y
  `/healthz/db`, páginas de error (JSON en `/api/*`). Todo lo que cambia estado es POST: nunca poner una acción que escribe en un GET.
- `limitador.py`: 429 por ventana deslizante en memoria (IA, sync manual, importar, OAuth, /admin y un tope general por IP). Por proceso, no exacto.
- `auditoria.py` + tabla `auditoria` (migración 0029, solo INSERT/SELECT para el rol de la app): poner `@auditar("accion")` DEBAJO de
  `@login_requerido` en toda ruta nueva que cambie datos reales o plata y agregar su etiqueta en `ETIQUETAS` (un test lo exige). Tacha tokens/claves.
- Macros de `_ux.html`: `titulo_html`/`sub_html` pasan por `utils.html_seguro` (lista de etiquetas permitidas): igual, escapar lo externo antes.
- Claves rotables sin cortar a nadie: `TOKEN_ENCRYPTION_KEY` (+ `_ANTERIOR`, `rotar_clave.py`) y `FLASK_SECRET_KEY` (+ `_ANTERIOR` → `SECRET_KEY_FALLBACKS`).
- Los syncs/tareas abren `db.conexion_usuario(usuario_id, cuenta_id)` SIEMPRE con `cuenta_id` (RLS por cuenta activa, migración 0010).
- Dependencias: rangos acotados en `requirements.txt` (no `==`), Dependabot semanal y `pip-audit` en CI; al subir Flask/cryptography/psycopg probar un sync real.
- Email del usuario: se lee de `/users/me` de Mercado Libre al crear la cuenta; los usuarios viejos con `meli-<id>@pendiente.corelux.app` lo
  completan en su próximo login (`registro._completar_email_pendiente`, nunca pisa un email real ni uno ya tomado: `usuarios.email` es único).
  `ADMIN_EMAIL` tiene que ser ese mismo email para entrar a `/admin` y `/admin/salud` (panel de salud del sistema, `salud_sistema.py`).
- Horas de venta: Mercado Libre manda `-04:00` aunque Argentina es UTC-3; `ventas_sync._fecha_hora_argentina` convierte al ingresar y marca `ventas.hora_normalizada`.
  Las filas viejas (false) se corrigen con `normalizar_horas.py --aplicar` (vista previa por defecto; aplicado el 2026-10-02).
- IA: `deepseek-flash` RAZONA y con `max_tokens` chico (200) se quedaba sin presupuesto: respuesta vacía y 8 s (coach, optimizar título…). `ia_asistente.parametros_extra()`
  apaga el razonamiento para DeepSeek (`IA_PARAMETROS_EXTRA` lo reemplaza) y los reintentos triplican el presupuesto. Ya no hay que subir los `max_tokens` a ojo.
- `cache_db.py` (tabla `cache_valores`, migración 0032): caché compartida por cuenta y por todos los procesos. Preferirla a un `_cache_*` en memoria (4 copias en producción y riesgo de mezclar cuentas). El coach de IA ya la usa.
- ⚠️ **Desplegar SIEMPRE con `python desplegar.py`** (desde CoreLux-SaaS): verifica carpeta/git, corre `predeploy.py`, despliega con `--build-arg GIT_SHA`, confirma que `/healthz` informa esa versión y, si el deploy falla y producción no responde, VUELVE SOLO a la última release buena. La imagen se niega a construirse si falta una dependencia (`verificar_dependencias.py`): el 2026-10-06 faltaba `packaging` (gunicorn lo importa y antes llegaba con Celery), la imagen arrancaba y se caía y producción estuvo caída; el deploy del 2 de octubre había fallado por lo mismo sin que se notara. Quitar una dependencia es quitar también lo que traía de rebote. Un `fly deploy` a mano desde otra copia del proyecto ya dejó código viejo en producción.
- ⚠️ **Probar siempre también SIN Redis**: la PC del dueño tiene Redis y Fly no. Un `cache.get()` directo habría dado 500 en todas las páginas al desplegar. Usar
  `cache.leer()/guardar()` (nunca lanzan) y, antes de un deploy, correr `REDIS_URL=redis://localhost:6399/0 pytest` y el recorrido de pantallas con ese mismo valor.
- `docs/RUNBOOK.md`: deploy, rollback, rotación de claves, tope de conexiones del pooler (`máquinas × workers × DB_POOL_MAX ≤ 12`), sync que no anda.

## Plan de mejoras (`PLAN_MEJORAS.md`, 243 ítems) — lo que ya cambió y las reglas que dejó (2026-10-02)
Se ejecuta por tandas, cada una commiteada y verificada. El dueño delegó las decisiones técnicas y de UX (puliendo, no agregando).
- **Navegación**: `nav_config.GRUPOS_NAV` define 7 secciones (Inicio, Día a día, Ventas y ganancia, Precios y costos, Stock, Publicaciones, Crecimiento);
  cada pantalla pertenece a una sola y las demás de la sección salen como pestañas. Barra inferior en el celular. `tests/test_navegacion.py` exige que
  todo `active_nav` esté en una sección. Para agregar una pantalla: sumarla ahí, no en el HTML del menú.
- **Modo beta**: `config.PAGOS_HABILITADOS = bool(MP_ACCESS_TOKEN)`. Sin token, la prueba no bloquea el acceso, planes/suscripción dicen "beta gratuita" y Referidos se oculta.
- **Celery ya no existe** (ni `rate_limiter.py`, `tasks/`, `motor_combos.py`). `app._en_segundo_plano(funcion, *args)` es un hilo. El `scheduler.py` (APScheduler) corre
  con un advisory lock de Postgres: un solo proceso ejecuta los trabajos (sync cada 4 min, salud de tokens por hora, competencia/tendencias a diario).
- **Panel de publicación** (`publicacion_edicion.py`): MeLi no deja cambiar el título de una publicación con ventas ni reabrir una cerrada ("closed" es irreversible);
  el límite del título depende de la categoría. Stock absoluto (PUT), nunca incremental; un POST no se reintenta solo. Las publicaciones sin variantes se guardan como
  variante `<id>_unica` y el stock va a nivel ítem. Las ventas manuales también descuentan stock en MeLi (`stock_meli.py`, migración 0034).
- **Confirmar decisiones**: `confirmarDecision(...)` (modal de `base.html`, devuelve una Promesa) en lugar de `confirm()`; todo cambio de plata muestra antes/después.
- **Tests de guarda** que fallan si se rompe un patrón: fechas, caché, `conexion_admin` solo en la lista permitida, `cuenta_id` en las conexiones, filtros de plantillas,
  `type=` en los botones, navegación, imagen Docker (sin respaldos ni vistas previas) y `tests/test_javascript.py`.
- ⚠️ **JavaScript sin compilador**: borrar una función que todavía se llama desde el arranque de `global.js` corta la inicialización de TODAS las pantallas (pasó con
  `cargarHud()` y llegó a producción). `test_javascript.py` lo detecta; antes de dar un cambio de JS por bueno, mirar también la consola del navegador, no solo la pantalla.
- ⚠️ Una captura tomada a mitad de una animación muestra números o elementos a medio dibujar: antes de reportar un bug visual, medirlo con el DOM, no con la captura.
- Vistas previas con datos reales: cualquier carpeta `static/_prev` se borra antes de commitear/desplegar (está en `.gitignore` y `.dockerignore`).
- **Hechos verificados contra MeLi real (2026-10-02)**: (a) `seller_reputation.transactions.ratings` llega como `positive 0 / neutral 1 / negative 0` = "100 % neutral" =
  MeLi ya no informa calificaciones de vendedor: `reputacion.interpretar_ratings` lo trata como "sin dato" y se enlaza a Opiniones. (b) `GET /categories/{id}` da
  `max_title_length = 60` pero los títulos reales miden 62-113 (MeLi los arma desde el nombre de familia): no existe un "MeLi trunca a 60"; el puntaje SEO solo penaliza
  lo corto, el texto promocional y las palabras repetidas. (c) `GET /trends/MLA/{categoría raíz}` trae ruido ajeno al rubro ("slots casino"); las categorías hoja de la
  cuenta (`productos_padre.category_id`, sin llamadas a MeLi) dan términos del rubro: `tendencias.obtener_tendencias_del_catalogo`, cacheado 6 h en `cache_db`.
- **Rankings siempre por MODELO**, nunca por publicación/talle: `dashboard.top_modelos` (clave `utils.limpiar_titulo_modelo`). Si aparece otro "top" por título, es el mismo error.
- **Dashboard**: orden hoy → qué hago → números → este mes → 14 días → detalle → "Más análisis" (plegado). Hasta las 18 el hero compara con AYER A ESTA HORA
  (`dashboard.ganancia_de_ayer_hasta_la_hora`; cada venta de `calcular_ganancia_real` lleva `momento` en hora argentina), después con el promedio de 14 días.
- **/admin**: `admin_usuarios.py` (días de prueba, activos en 7 días, `extender_prueba`); `POST /admin/usuario/<id>/extender_trial` está auditado. Los usuarios viejos con
  email `…@pendiente.corelux.app` no pueden entrar a /admin hasta que su email real se complete en el próximo login.
- **Aislamiento por cuenta activa (RLS)**: TODA tabla con `cuenta_id` filtra también por `app.cuenta_actual` (política como la de `ventas`, migración 0010). Una migración
  que "recree" una política (la 0014 de Tendencias lo hizo) la puede dejar solo por usuario y mezclar las cuentas de un usuario Elite: la 0036 lo restituyó y
  `tests/test_rls_cuenta_activa.py` lo exige para toda tabla (salvo `alertas_usuario`, `auditoria`, `feedback`, `meli_tokens`, que son de la persona). Al escribir una
  migración que toque políticas, copiar siempre la forma con `cuenta_actual` y comparar como TEXTO (castear '' a bigint explota).
- **Migraciones y pruebas**: `predeploy.py` corre las pruebas contra la base REAL y falla si algo se omite; una prueba que dependa de una migración pendiente lo deja en
  rojo. Dos salidas: el código tolera la columna ausente (`preferencias.py`) o se aplica `python migrate.py` ANTES (son aditivas e idempotentes). 0034-0036 ya están aplicadas.
- **Preferencias por cuenta** (`/cuenta`, `preferencias.py`): hoy `cuentas_meli.margen_minimo` (0-60, 15 por defecto), expuesto como `margen_minimo` en Jinja y
  `window.MARGEN_MINIMO` en JS. No hardcodear 15: es referencia visual, no cambia cálculos. "Descargar mis datos" (`mis_datos.py`) lee con la conexión del usuario (RLS), sin tokens.
- **Sincronización: costo de régimen medido** (`python medir_sync.py <usuario_id> <cuenta_id>`, corre 2 syncs reales y cuenta llamadas): ~19 por ciclo y cuenta. No volver a pedir en cada
  ciclo lo que casi no cambia: el stock de convivencia (`sincronizador.decidir_convivencia`, firma last_updated+sold_quantity+available_quantity; ojo: `available_quantity` es el
  stock de FULL, no el propio), el impacto en reputación (2 h) y el dinero retenido (1 h) usan `cache_db`. Las escrituras de reclamos van SIEMPRE ordenadas por id (deadlock entre scheduler y webhook).
- **Errores de MeLi**: `meli_errores.explicar_respuesta(r)` es la única forma de contarle un rechazo a la persona (sin códigos, JSON ni inglés). Toda escritura a MeLi tiene que mirar el
  resultado: crear/eliminar descuentos lo ignoraban y parecía que había funcionado.
- ⚠️ Al correr pruebas y commitear en el mismo comando: nunca con `;` ni detrás de un pipe (`| tail` esconde el código de salida): ya se subió un commit con pruebas en rojo.
- **Campana de avisos (2026-10-06)**: UN solo lugar para "qué tengo que mirar ya". `dashboard.armar_avisos` arma, en `/api/ticker`, reclamos que afectan la reputación,
  preguntas sin responder, publicaciones activas sin stock y devoluciones (más la salud <65, que suma el JS); `global.js` los junta con las alertas guardadas
  (`/api/alertas/pendientes`, hoy la salud de tokens, con "Listo") en `_avisos` y de ahí salen la campana, los contadores del menú (`_actualizarBadgeNav`) y un toast SOLO cuando
  algo subió (la primera lectura de la sesión no avisa). Para sumar un aviso nuevo: un candidato más en `armar_avisos` (con su prueba), no otro contador en el HTML.
  Los textos externos entran por `textContent`. No hay mails ni notificaciones del navegador todavía (falta definir proveedor de mail).
- **Tablas ordenables (2026-10-07)**: `static/js/tablas.js` (se carga en `base.html`). `<table data-ordenable>` + `<th data-orden="num|texto">` (y `data-primero="asc|desc"` si la primera vez no es la natural);
  la celda usa su `data-orden` si lo tiene (fechas ISO, números sin formato; vacío = va siempre al final) o su texto leído en formato argentino. Las filas `ux-subfila` viajan con su fila, y si la lista está
  recortada con «ver más» se ordena TODO y se vuelve a recortar. En celular (tabla de tarjetas) aparece solo un selector «Ordenar por». Los títulos largos van en `<span class="titulo-1l" title="…">` (una línea
  con «…»; un test exige el `title`). Para sumar una tabla: solo los atributos, sin JS nuevo; `tests/test_tablas.py` ejecuta la lógica con node.
- **Cargos mensuales de MeLi y la factura (2026-10-07)**: la factura (`/billing/integration/.../summary/details`) trae cargos que NO están en ninguna venta: `CESM` mantenimiento de eShop, `CSTP`
  reputación, `CFWA` almacenamiento en FULL, `CFRS` retiro/descarte de stock en FULL y `CDSD` devolución (neta de su anulación `BDSD`). A los vendedores se les acredita la diferencia, así que son plata que sale:
  `facturacion.cargos_fuera_de_ventas` los reparte POR DÍA dentro de cada período de facturación (el abierto, entre los días ya transcurridos) y `calcular_ganancia_real` los descuenta
  (`resumen.raw.ganancia_neta` = real; `ganancia_neta_ventas` = lo que dejó cada venta, que es con lo que el Dashboard compara un día contra el promedio; el punto de equilibrio los suma a los costos
  fijos y NO al margen de contribución). Se guardan en `cache_db` (`factura_fijos:<key>`: cerrada 90 días, abierta 30 min; si MeLi no responde se usa lo último guardado y se avisa). Las retenciones/percepciones
  (IIBB…) siguen SIN restar. La tabla de la factura se arma por CÓDIGO (`facturacion.agrupar_factura`): el grupo «Cargos de envíos full» que informa MeLi es en realidad almacenamiento y retiros de FULL, no envíos.
  Flex NO está en la factura de MeLi: entra en «Cargos por envíos» como línea aparte (bruto) y su reintegro (10 %) en «Bonificaciones»; el total de la factura de MeLi no cambia. Si hay que
  sumar otro cargo mensual: agregarlo a `CARGOS_FUERA_DE_VENTAS` con su prueba. Ojo: ya hubo una factura de otra cuenta con tipos que esta no tenía; antes de asumir que un código no existe, mirar `ver_factura`-style con la API.
- **Condición fiscal: NUNCA se supone (2026-10-07, migración 0037)**: no todos los vendedores son monotributistas (hay responsables inscriptos y quien todavía no está inscripto). `cuentas_meli.condicion_fiscal`
  (`monotributo | responsable_inscripto | sin_inscripcion`; NULL = no la sabemos) la declara la persona en el onboarding (4.ª pregunta), en Mi cuenta (`#condicion-fiscal`) o en la propia pantalla de Monotributo
  (`POST /cuenta/condicion_fiscal`, auditado). `fiscal.capacidad_monotributo` alimenta `capacidades.monotributo`: SOLO un `False` (declaró otra condición) esconde la pestaña y el atajo Ctrl+K;
  sin declarar no esconde nada y la pantalla pregunta en vez de calcular; el panel de Monotributo del Dashboard solo aparece para monotributistas declarados. Cualquier cosa nueva que dependa de la condición
  fiscal tiene que mirar `fiscal.obtener(...)`. Mercado Libre da el CUIT/DNI (`GET /users/me` → `identification`) pero NO la condición ante ARCA (se probó: no hay endpoint). Confirmarla sin preguntar
  requeriría el padrón de ARCA (constancia de inscripción) con un certificado propio de CoreLux y el CUIT que da MeLi: pendiente, lo tiene que gestionar el dueño. Los textos nuevos dicen ARCA (ex AFIP).
- **«Día a día» es UNA pantalla (2026-10-07)**: `/dia` (`dia_vista`) junta Despacho, Preguntas, Pendientes y Reputación una debajo de la otra; las 4 pestañas de la sección tienen `href: /dia` + `ancla` en
  `nav_config` (la sección lleva `una_pantalla: True`: no hay «más usada») y saltan a cada parte, marcándose solas según lo que se mira (script de `dia.html`). Cada parte es una plantilla parcial
  `_dia_<parte>.html` (antes eran las pantallas `despacho.html`, `preguntas.html`, `logros.html`, `reputacion.html`, que ya no existen) con su contexto en `app._contexto_despacho/_contexto_logros/_contexto_reputacion`
  (Preguntas carga todo por fetch). Si una parte falla, las demás se muestran (`errores`); la cuenta desconectada se manda a reconectar (`_Salir`). Los links viejos (`/despacho?fecha=`, `/preguntas`, `/logros`,
  `/reputacion`) redirigen a su ancla (`_url_dia`). Para sumar una parte: plantilla `_dia_*.html`, su contexto, su `<section id>` en `dia.html` y su pestaña. Los ids y los `const/let` globales de los scripts de
  las partes no pueden repetirse (una prueba lo exige).
- **Refresco del token de MeLi, de a uno por cuenta (2026-10-07)**: el `refresh_token` es de UN SOLO USO. `token_manager._refrescar_de_a_uno` refresca con un candado por cuenta en el proceso + un
  `pg_advisory_xact_lock(BASE_LOCK_REFRESCO + cuenta_id)` entre procesos (2 máquinas × 2 workers), relee el token tras esperar y guarda todo en la misma transacción: antes, dos pedidos que veían el token vencido a la
  vez gastaban el mismo refresh, el segundo recibía `invalid_grant` y la cuenta se marcaba desconectada sin estarlo. Un 401 usa `refrescar_token_rechazado` (no refresca de nuevo si otro ya cambió el token).
  Nunca se levanta una excepción DENTRO de esa transacción si hay que confirmar algo (la desconexión por `invalid_grant` se levanta después). `tests/test_token_refresco.py` reproduce la carrera con hilos. El advisory lock + `lock_timeout` se probó contra el Postgres real (espera, `LockNotAvailable`, sin `lock_timeout` pegado en el pool).
  ⚠️ El refresco real contra MeLi NO se pudo probar desde la PC: con las credenciales del `.env` local MeLi contesta `invalid_client` (no gasta el refresh_token ni desconecta la cuenta). Para verlo en vivo hay que
  mirar los logs de Fly tras el deploy (un refresco por cuenta cada ~6 h, sin `invalid_grant`). No forzar `expira_en` en cuentas reales desde la PC.
- **Auditoría externa de 15 hallazgos (2026-10-07)**: se verificó cada uno contra el código y la base antes de tocar nada. NO eran ciertos: (4) las políticas RLS con `cuenta_id::text` no pierden los índices
  (el `EXPLAIN` usa `idx_ventas_cuenta_fecha`; castear el setting no cambia el plan por el `OR` con constantes — lo que sí limita es que el filtro de cuenta no entra al índice: si hay muchos tenants, la mejora real es
  `cuenta_id = ANY(ARRAY(SELECT id FROM cuentas_meli WHERE usuario_id = …))` en la política, medida con datos grandes y probada con los tests de RLS); (7) `ventas.codigo_postal` y `localidad` NO están huérfanas (2.692 filas
  con valor; `flex.py` y `ventas_sync.py` las usan: un test impide borrarlas); (9) nada marca `eliminado_en` (el borrado es físico), no hay nada que purgar; (13) `deploy/gunicorn_config.py` no se usaba en Fly. Los índices de
  claves foráneas se detectan con `pg_constraint` (no con la lista de la auditoría: `referrals` ya tenía los suyos) y una prueba exige que toda FK tenga índice.
- **Auditoría externa de frontend, 19 puntos (2026-10-07)**: también se verificó cada uno contra el código, la base y un navegador real antes de tocarlo. NO eran ciertos: (4) el círculo de «despachado» ya tiene borde naranja
  (`ux.css`, que carga después de `style.css`, pisa el `--text-faint` que la auditoría leyó); (9) el estado vacío de Despacho ya tiene su botón primario («Traer ventas nuevas») justo arriba: un segundo primario lo rompería; (13) las tablas
  de Ganancia Real están dentro de `.panel` / `.ux-detalle-cuerpo`, que ya tienen `overflow-x: auto` (medido a 375 px: la página no scrollea de costado); (5) los 6 `<details>` cerrados son una línea cada uno y son la regla «detalle plegado»:
  no se pasaron a pestañas. Parciales: (12) `ventas.id_variante` no tiene ningún NULL (el vacío normal es `''`), se endureció igual; (17) el form del modo foco ya se escondía por `.ux-periodo`, solo se sacó el selector muerto; (19) la ventana del
  asistente quedaba cortada 41 px a la izquierda (no generaba scroll global: es `position: fixed`). Sí estaban mal y se corrigieron: el botón primario de Ganancia Real (ahora es la descarga del PDF, debajo del número; «Ver período» y el aviso
  informativo pasaron a secundarios), salida desde el hero del Dashboard (`#hero-acciones`: sin costo → /costos, pérdida → /metricas, bien → «Ver el detalle»), pastilla violeta en Stock masivo, `destroy()` de los gráficos que se rearman,
  promesas compartidas que no se envenenan (`_compartida`), campos que viajan en Stock masivo (solo los cambiados), hora de Argentina en la cuenta regresiva (`ahoraArgentina()`), tooltips del tema claro, margen con facturado 0, acordeón con teclado.
  ⚠️ **Estrategia para sacar `'unsafe-inline'` del `script-src`** (`seguridad.CSP`): hay ~143 manejadores inline (`onclick=`…) y ~42 `<script>` inline. (1) `static/js/ux.js` trae el despachador `data-click` / `data-change` / `data-input` /
  `data-keyup` (+ `data-<evento>-args` JSON, `$el`, `$ev`, `$valor`, `$form`, `$closest:.sel`, `data-aislar`, `role="button"` con Enter/espacio): migrar una pantalla = cambiar sus `onclick="f(this, 3)"` por `data-click="f" data-click-args='["$el", 3]'`
  (en Jinja: `{{ [a, b]|tojson }}` entre comillas simples; los ids de MeLi siempre como texto). (2) `tests/test_correcciones_frontend.py` fija un tope de manejadores (`PRESUPUESTO_INLINE`: solo baja) y exige que las pantallas ya migradas
  (`SIN_INLINE`) no vuelvan a tener ninguno; migradas hoy: `_ux.html`, Ganancia Real, Stock masivo, Despacho, Dashboard. (3) Faltan `base.html` (menú, modales, chat), Costos, Tendencias, Precios, Embudo, Promociones y los strings de `global.js`.
  (4) Cuando no quede ninguno: un nonce por pedido (`g.csp_nonce` + `nonce="{{ csp_nonce }}"` en cada `<script>` inline) y `script-src 'self' 'nonce-…'`; con el nonce puesto el navegador IGNORA `'unsafe-inline'`, así que activarlo antes de migrar todo rompe
  la app. Probar antes con `Content-Security-Policy-Report-Only`. `style-src 'unsafe-inline'` se queda (840 `style=`: bajo riesgo). Al probar en el navegador local, NUNCA enviar formularios de verdad (`form.submit()` real manda un POST al servidor local, que usa la base de producción).
- **Respaldos** (`respaldo.py`): fuera del proyecto (`~/CoreLux-respaldos`), se niega a escribir adentro, cifra con `RESPALDO_CLAVE` (Fernet). Ver `docs/RUNBOOK.md`.

## `cosas.txt` — bugs reportados por el usuario usando la app real
Archivo en la raíz (no es código, son notas del usuario navegando la
app real como usuario nuevo). Es la fuente de verdad de bugs
reportados — antes de decir "no hay más bugs conocidos", leelo. Al
2026-09-30, de sus 16 ítems originales, 11 ya se arreglaron (repartidos
en 3 commits "fix: batch de bugs reportados..."). Quedan pendientes o
sin confirmar en vivo: el resumen de números de hoy en Stock, un campo
para cargar el costo de entrega Flex por zona (HECHO, ver Entrega Flex), el
motivo real de reclamos (HECHO: el texto sale de
`/post-purchase/v1/claims/reasons/{id}`) y cuáles afectan la reputación (HECHO,
ver Reclamos arriba), los períodos de Facturación (HECHO: el 9 al 8 es el ciclo real de
MeLi), y un 403 de MeLi al buscar en Tendencias por término/categoría.

## Datos de entorno
- `.env` necesita: `DATABASE_URL` (pooler de **sesión**, no de
  transacción — el puerto importa para que RLS sea confiable),
  `DATABASE_URL_ADMIN`, `MELI_CLIENT_ID/SECRET/REDIRECT_URI`
  (`REDIRECT_URI` productivo: `https://corelux.app/callback`),
  `FLASK_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `IA_API_KEY`/`IA_BASE_URL`/`IA_MODEL`
  (opcional, para el coach de Logros y Costos por chat — cualquier
  proveedor compatible con Chat Completions de OpenAI sirve; en uso
  actual: DeepSeek, `https://api.deepseek.com`, `deepseek-flash`.
  Antes se llamaban `OPENROUTER_*` porque se empezó con OpenRouter,
  se renombraron 2026-09 al cambiar de proveedor)
- `FLASK_DEBUG` SIEMPRE en `false` en cualquier entorno expuesto
  públicamente (ngrok, Fly.io) — con debug activo, un error muestra
  una consola de Python interactiva a cualquiera que la vea.
- Migraciones corridas hasta `0033_feedback.sql` (0029 auditoria, 0030 sub_estado, 0031 hora_normalizada, 0032 cache_valores, 0033 feedback) — 
  verificá `migrate.py --status` contra Supabase real antes de asumir
  cuál es la última aplicada, el número más alto en `migrations/` no
  siempre coincide con lo corrido de verdad.
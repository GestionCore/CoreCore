# CoreLux — contexto de traspaso para Claude Code

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
- **Entrega Flex por zona** (`flex.py`, migraciones 0018–0020): en Flex el
  vendedor entrega con su propia logística y MeLi reporta `costo_envio = 0`;
  el costo real lo cobra esa logística por distancia (3 zonas). El usuario
  carga 3 precios (`cuentas_meli.flex_tarifa_zona1..3`) en Costos.
  `ventas.costo_envio` = lo que informa MeLi + `ventas.costo_flex`, así
  Ganancia Real/Dashboard/Facturación/Fiscal lo suman sin tocar sus
  cálculos; `ventas_sync` conserva `costo_flex` al reprocesar una orden y
  TODA asignación de zona mueve `costo_flex` y `costo_envio` juntos
  (`flex._aplicar_zona`, una sola sentencia para cualquier cantidad de
  órdenes). `ventas.flex_zona`: 1–3, o 0 = "sin costo" (entrega el propio
  vendedor); NULL = pendiente. La zona se resuelve así, en este orden: lo que
  el usuario eligió a mano para un código postal/localidad
  (`cuentas_meli.flex_zonas_memoria`) > regla de distancia opcional (CP de
  salida + hasta cuántos km llega cada zona; MeLi trae las coordenadas
  exactas del destino en `/shipments/{id}` y resuelve el CP de salida en
  `/countries/AR/zip_codes/{cp}`) > a mano (por localidad en Costos, por
  envío en Despacho). Aplicar la regla siempre muestra una vista previa
  (envíos y costo por zona) y el usuario confirma. Una venta ya asignada
  queda valuada al precio de ese momento; cambiar tarifas solo la recalcula
  si el usuario lo pide. Ganancia Real avisa cuántos Flex del período siguen
  sin zona. `ventas_sync._completar_datos_de_envio` completa de a 40 por
  pasada el tipo de logística y el destino de ventas viejas (60 días).
  ⚠️ Los km de la regla son una estimación en línea recta desde el centro
  del CP de salida: sugerirle al usuario contrastarlo con lo que le factura
  su logística.

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
  no gunicorn+systemd+nginx a mano (los archivos de `deploy/` para esa
  ruta vieja siguen en el repo por si hace falta, pero no son el
  camino real hoy).
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

## `cosas.txt` — bugs reportados por el usuario usando la app real
Archivo en la raíz (no es código, son notas del usuario navegando la
app real como usuario nuevo). Es la fuente de verdad de bugs
reportados — antes de decir "no hay más bugs conocidos", leelo. Al
2026-09-30, de sus 16 ítems originales, 11 ya se arreglaron (repartidos
en 3 commits "fix: batch de bugs reportados..."). Quedan pendientes o
sin confirmar en vivo: el resumen de números de hoy en Stock, un campo
para cargar el costo de entrega Flex por zona (HECHO, ver Entrega Flex), el
motivo real de reclamos (falta ver logs de un sync real para terminar
de mapear los `reason_id` de MeLi), si los períodos de Facturación
(9 al 8 del mes siguiente) están realmente mal o es el ciclo real de
MeLi, y un 403 de MeLi al buscar en Tendencias por término/categoría.

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
- Migraciones corridas hasta `0020_flex_distancia.sql` — 
  verificá `migrate.py --status` contra Supabase real antes de asumir
  cuál es la última aplicada, el número más alto en `migrations/` no
  siempre coincide con lo corrido de verdad.
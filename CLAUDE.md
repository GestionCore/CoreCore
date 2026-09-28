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
  (OpenRouter) convierte una descripción en lenguaje natural en un
  gasto estructurado, pregunta el período si falta, y SIEMPRE pide
  confirmación explícita antes de guardar — nunca escribe directo.
  `gastos_operativos` ahora soporta `recurrente` + `fecha_fin`, con
  prorrateo por día en `costos.py` cuando el período elegido es más
  corto que un mes.

## Lo que NO existe todavía (no asumas que sí)
- Puente de WhatsApp (Baileys) — comentado en `iniciar_corelux.bat`
- Auditoría automática de devoluciones/cancelaciones más allá de lo
  que ya cubre `ventas_sync.py`
- Cobro por Mercado Pago
- UI de selección de cuenta para el plan Elite (la función de backend
  `obtener_cuentas_de_usuario` existe, la UI no)
- Rediseño del Dashboard (gráficos, más variedad — hoy son cuadros de
  resumen chicos nomás)
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
- La identidad visual (estética Tron/vaporwave) es intocable — mejorar
  el código sí, cambiar el look no.
- Entregar solo los archivos que cambiaron, respetando la carpeta real
  del proyecto (no volver a comprimir todo el proyecto entero cada vez).

## Datos de entorno
- Dominio estático de ngrok: `twister-casket-routing.ngrok-free.dev`
  (app de Mercado Libre Developers separada de la personal del usuario)
- `.env` necesita: `DATABASE_URL` (pooler de **sesión**, no de
  transacción — el puerto importa para que RLS sea confiable),
  `DATABASE_URL_ADMIN`, `MELI_CLIENT_ID/SECRET/REDIRECT_URI`,
  `FLASK_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `IA_API_KEY`/`IA_BASE_URL`/`IA_MODEL`
  (opcional, para el coach de Logros y Costos por chat — cualquier
  proveedor compatible con Chat Completions de OpenAI sirve; en uso
  actual: DeepSeek, `https://api.deepseek.com`, `deepseek-flash`.
  Antes se llamaban `OPENROUTER_*` porque se empezó con OpenRouter,
  se renombraron 2026-09 al cambiar de proveedor)
- `FLASK_DEBUG` SIEMPRE en `false` si la app está expuesta por ngrok —
  con debug activo, un error muestra una consola de Python interactiva
  a cualquiera que la vea.
- Verificá que el esquema de Supabase tenga aplicadas todas las
  migraciones (`ALTER TABLE`) de sesiones anteriores — el archivo
  `schema/01_schema_multitenant.sql` puede no reflejar 1:1 lo que ya
  está corrido en la base real si alguna quedó pendiente.
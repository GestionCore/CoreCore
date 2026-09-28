# CoreLux — Puerto completo de Santi Mens a multi-tenant

## Estado: las 21 páginas del original están portadas, más sincronización automática

Stock, Stock Masivo, Despacho, Ganancia Real (con Ads y Reclamos), Costos, Facturación, Flujo de Caja, Comparador Logística, Historial de Precios, Promociones, Tendencias, Espía de Competencia, Embudo de Conversión, Reputación, Logros, Publicidad, Timeline de Publicación, Exportador a Redes, y el Dashboard personalizable — más el sincronizador real contra la API de MeLi, corriendo automáticamente cada 4 minutos **para todas las cuentas activas**, no una sola.

## Migración de psycopg2 a psycopg3

Esta versión usa **psycopg 3** (`psycopg[binary,pool]`), no `psycopg2-binary`. El motivo: `psycopg2-binary` todavía no tiene una versión precompilada para Python 3.14, y compilarla desde cero en Windows exige `pg_config`, que no viene instalado ahí. `psycopg3` sí trae wheels precompilados que cubren versiones nuevas de Python — así que en vez de forzar la instalación vieja, se migró el proyecto.

**Si ya tenías `psycopg2-binary` instalado y funcionando en tu máquina**, este cambio no te afecta para mal — psycopg3 funciona igual de bien en Python más viejos. Solo corré `pip install -r requirements.txt` de nuevo para traer la librería correcta.

Dos diferencias reales que aparecieron migrando (no cosméticas):

1. **`SET app.usuario_actual = %s` no funciona en psycopg3** — Postgres no acepta parámetros del lado del servidor (los que usa psycopg3 por default) dentro de una sentencia `SET`. Se cambió a `SELECT set_config('app.usuario_actual', %s, false)`, una función común que sí los acepta y hace exactamente lo mismo.
2. **Filas mixtas por posición y por nombre en el mismo cursor**: `psycopg2.extras.DictCursor` permite acceder a una fila TANTO por posición (`fila[0]`) COMO por nombre (`fila["columna"]`) al mismo tiempo — el equivalente de psycopg3 (`dict_row`) solo permite por nombre. Encontré 3 archivos con esta mezcla (sobre todo `costos.py`) y los reescribí explícitamente por nombre de columna, agregando alias donde hacía falta (ej: `AVG(costo_envio) AS envio_promedio`) para no depender de nombres de columna implícitos.

Todo esto se probó de nuevo por completo: aislamiento RLS entre cuentas, las 24 rutas de la app, y 100 pedidos concurrentes reales de 5 cuentas distintas — mismos resultados que con psycopg2.

## Auditoría de producción (encontrado usando la app de verdad, no solo en pruebas)

Después de que la landing y el login fallaran al correr esto de verdad, hice una pasada buscando específicamente ese tipo de problema — cosas que "andan bien en la prueba" pero fallan con uso real:

- **`FLASK_DEBUG=true` como default en `.env.example`**: con debug activado y la app expuesta por ngrok, cualquier error muestra una consola de Python interactiva en el navegador de quien sea que la vea — ejecución de código remoto, no un detalle menor. Default cambiado a `false`, con un aviso bien visible en consola si alguna vez se arranca en `true`.
- **Faltaba `threaded=True` en `app.run()`**: sin esto, el servidor solo atiende un pedido a la vez — con usuarios reales se hubiera sentido lentísimo.
- **El pool de conexiones usaba `SimpleConnectionPool`**, que psycopg2 documenta explícitamente como "no se puede compartir entre threads" — agregar `threaded=True` sin cambiar esto hubiera introducido un bug de concurrencia nuevo. En su momento se cambió a `ThreadedConnectionPool` (de psycopg2); con la migración a psycopg3 (ver más abajo) pasó a ser `ConnectionPool` de `psycopg_pool`, pensado para multi-hilo desde el diseño. Probado con 100 pedidos concurrentes reales (con hilos de Python, no simulados) de 5 cuentas distintas mezcladas al mismo tiempo — sin errores, sin fugas de datos entre cuentas.

## Qué incluye

- Esquema completo de Postgres multi-tenant con Row Level Security (`schema/01_schema_multitenant.sql`)
- Flujo de OAuth 2.0 completo contra Mercado Libre, con renovación automática de tokens y manejo de `invalid_grant`
- Cifrado de tokens antes de guardarlos (Fernet)
- La identidad visual completa de Santi Mens, portada tal cual (CSS, JS, partículas, nav, ticker) — nada estético cambió
- El sincronizador real de catálogo contra la API de MeLi, con locks independientes por cuenta
- Todo probado de punta a punta contra una base Postgres real en cada módulo, no solo "se ve bien"

## Los 9 bugs reales encontrados y corregidos durante el port

Estos existían en el código original de Santi Mens, pero nunca se manifestaban con una sola cuenta — todos son del mismo patrón: **estado en memoria compartido entre TODAS las cuentas en vez de aislado por cuenta**, algo que solo se vuelve visible al pasar a multi-tenant.

1. **`ads.py`** — `_advertiser_cache` cacheaba por `site_id` solo ("MLA") — la primera cuenta contaminaba el advertiser_id de todas las demás.
2. **`facturacion.py`** — `_cache_periodos` era un único slot global; `_cache_resumenes` cacheaba por período sin cuenta_id.
3. **`logistica.py`** — `_cache_flex_habilitado` era un único slot global — la primera cuenta que chequeaba Flex definía la respuesta para todas.
4. **`tendencias.py`** — `_categoria_cache` era un único slot global — la categoría de la primera cuenta ("Ropa y Accesorios") quedaba fija para cualquier otra.
5-6. **`embudo_conversion.py`** — `_cache_embudo` y `_cache_zombies`, mismo patrón, dos veces.
7. **`sincronizador.py`** — `_candado_sincro` era un Lock único para todo el proceso — la cuenta B se hubiera bloqueado esperando mientras la cuenta A sincroniza, sin relación entre ellas.
8. **El esquema RLS original** — solo tenía política real en 3 de 21 tablas; el resto quedaba con RLS activado pero sin política, bloqueando todo acceso por default.
9. **`app.py` — faltaba `jsonify` en el import de Flask** — silenciosamente rompía los 19 endpoints que devuelven JSON hasta que se probó alguno específicamente. También faltaba `import requests` a nivel de módulo (usado en el exportador a redes) — el mismo tipo de error, encontrado por el mismo motivo: probarlo de verdad en vez de asumir que compilar alcanza.
10. **`sincronizador.py` (scheduler)**: la tarea periódica original sincronizaba UNA cuenta hardcodeada — ahora recorre todas las cuentas activas de la base, probado con 3 cuentas simultáneas.

Después de encontrar los primeros dos bugs de "import faltante", corrí un smoke test contra las 24 rutas GET de la app de una sola vez — todas respondieron 200, dando bastante confianza de que no quedan más bugs de ese tipo dando vueltas sin detectar.

## Un cambio estructural real (no un bug, una decisión de diseño)

En el esquema original de SQLite, `productos_variantes.id_padre` guardaba el `id_meli` (texto) de la publicación. En el esquema multi-tenant, apunta a la clave propia (`productos_padre.id`, un entero) — más simple y prolijo para los JOIN. Esto significa que escribir un ítem ahora sigue el patrón "upsert del padre con `RETURNING id`, después usar ese id para las variantes" en vez de escribir directo — probado con creación y actualización de un ítem real con 2 variantes.

## Onboarding: encuesta + tutorial guiado

La primera vez que alguien conecta su cuenta, antes de ver cualquier dato:

1. **Encuesta de 3 preguntas** (`/onboarding`): qué le importa más controlar, hace cuánto vende, y qué pantalla quiere ver primero al entrar. Se muestra ANTES de que termine la sincronización — no hace esperar innecesariamente por algo que tarda un segundo.
2. Con eso guardado, **`/` respeta la pantalla elegida**: si prefirió "Dashboard" o "Ganancia Real", ya no lo manda siempre a Stock.
3. **Tutorial guiado** la primera vez que entra a una página real: recorre el buscador, los tres menús principales, el botón de sincronizar y la barra de estado, con blur alrededor de todo lo que no está explicando en ese momento — con "Siguiente" y "Saltar tutorial" siempre visibles.

Esto agrega 3 columnas a `usuarios` (ver la migración de esquema abajo) y usa un flag de sesión (`mostrar_tutorial`) que se apaga solo la primera vez que el tutorial arranca, para que no vuelva a aparecer en visitas siguientes.

## Sesión de correcciones en vivo (con la app corriendo de verdad)

Después de que el usuario probó CoreLux contra su propia cuenta real de Mercado Libre, aparecieron problemas que ningún test contra datos simulados podía detectar:

- **Nunca existía un sincronizador de VENTAS.** `sincronizador.py` solo traía catálogo (publicaciones y stock) — nunca hubo código que trajera órdenes reales desde la API de MeLi. Se construyó `ventas_sync.py` de cero: incremental desde el arranque (guarda hasta qué fecha ya sincronizó en `cuentas_meli.ultima_sincronizacion_ventas` y la próxima vuelta arranca desde ahí, con un colchón de 2hs), extrae comisión, envío (proporcional si la orden tiene varios ítems), estado de despacho y comprador.
- **El error de RLS en `productos_padre` que parecía no resolverse**: `set_config(..., false)` (alcance de sesión) no es confiable contra el pooler de Supabase — se cambió a `is_local=true` (alcance de transacción), correcto para cualquier tipo de pooler.
- **Arranque automático + pantalla de espera**: al conectar la cuenta por primera vez, la sincronización arranca sola en segundo plano; mientras tanto, cualquier página protegida muestra una pantalla de espera prolija en vez de datos vacíos, hasta que `cuentas_meli.sincronizacion_inicial_completa` pasa a true.
- **La barra de navegación se apilaba** en dos líneas — las dos zonas del header estaban fijas a 50/50 en vez de repartirse según lo que necesita cada una.
- **Dos endpoints 404** (`/api/curva_talles`, `/api/oportunidades_seo`) que el JS de Stock ya llamaba pero nunca se habían construido del lado del servidor.
- **Bug real con datos de MeLi reales**: el campo `budget` de una campaña de Ads vino como número directo, no como `{"amount": N}` — rompía la página de Publicidad con cuentas reales.
- **Botones de 7/14/30 días** agregados junto a los selectores de período en Ganancia Real, Publicidad, Comparador Logística y Costos.
- **Revisión de textos**: se sacó lenguaje que "protesta de más" (comparaciones tipo "no estimaciones de terceros", "nunca vemos tu contraseña", "no solo si se sintió bien") en el login, la calculadora de costos y promociones — reemplazado por afirmaciones directas.
- **`iniciar_corelux.bat`** (provisorio): levanta `app.py` (con el venv activado) y `ngrok` cada uno en su propia ventana. La línea del puente de WhatsApp está comentada — todavía no existe ese módulo en CoreLux.

### Migración de esquema necesaria

Si ya corriste el esquema antes de esta vuelta, hace falta este ajuste en el SQL Editor de Supabase:

```sql
ALTER TABLE cuentas_meli
    ADD COLUMN ultima_sincronizacion_ventas TIMESTAMPTZ,
    ADD COLUMN sincronizacion_inicial_completa BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE usuarios
    ADD COLUMN onboarding_completo BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN prioridad_principal TEXT CHECK (prioridad_principal IN ('ganancia', 'stock', 'publicidad', 'competencia', 'todo')),
    ADD COLUMN experiencia_meli TEXT CHECK (experiencia_meli IN ('nuevo', 'en_crecimiento', 'consolidado')),
    ADD COLUMN pantalla_preferida TEXT CHECK (pantalla_preferida IN ('dashboard', 'stock', 'metricas'));

-- Si ya tenías cuentas conectadas ANTES de esta migración, esto evita que
-- les aparezca la encuesta de onboarding de golpe la próxima vez que
-- entren — solo la ven las cuentas genuinamente nuevas de acá en más.
UPDATE usuarios SET onboarding_completo = true;
```

## Puesta en marcha

### 1. Base de datos (Supabase)

Correr `01_schema_multitenant.sql`, y crear los dos roles:

```sql
CREATE ROLE app_backend LOGIN PASSWORD 'una-password-fuerte-1';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_backend;

CREATE ROLE app_admin LOGIN PASSWORD 'una-password-fuerte-2' BYPASSRLS;
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_admin;
```

### 2. Variables de entorno

```bash
cp .env.example .env
```

Completá las dos `DATABASE_URL`, `MELI_CLIENT_ID`/`SECRET`/`REDIRECT_URI`, `FLASK_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` (comandos para generarlas en el `.env.example`). `IA_API_KEY` es opcional — sin ella, Logros funciona igual, solo sin el mensaje "coach" (y el Chat IA / Costos por chat avisan que falta configurar la IA en vez de responder).

### 3. Instalar y correr

```bash
pip install -r requirements.txt
python app.py
```

Con ngrok corriendo en paralelo (`ngrok http 5000`), entrá a tu URL y probá "Conectar con Mercado Libre" — al conectar una cuenta real, el sincronizador va a traer tu catálogo real por primera vez (botón "Sincronizar" en el panel de Stock).

## Qué queda para más adelante (a propósito, no es parte de "portar lo que ya existía")

- El aviso por WhatsApp cuando cambia un estado/stock/foto de competidor queda comentado — se reactiva cuando se porte el puente de WhatsApp (Baileys)
- La auditoría automática de devoluciones/cancelaciones (`devoluciones_sync.py`, `ventas_sync.py`) — la sincronización automática ya corre para catálogo, competencia y combos, pero esta pieza específica todavía no
- Cobro de suscripción (Mercado Pago) — pospuesto a propósito desde el principio
- El plan Elite multi-cuenta tiene la base de datos lista (`obtener_cuentas_de_usuario`) pero falta la UI para cambiar entre cuentas

## Estructura

39 archivos Python + 21 templates HTML — ver `app.py` para el mapa completo de rutas; cada módulo de negocio tiene su propio archivo nombrado igual que en el proyecto original.

# CoreLux — contexto completo del proyecto (para pasarle a otra IA)

> Pegá este documento entero al empezar una conversación con otra IA. Está escrito para que, leyéndolo, entienda qué es el sistema, cómo está armado, qué decisiones ya se tomaron (y por qué),
> qué no tocar y cómo trabaja el dueño. Estado al **2026-10-07**. Lo más detallado y siempre vigente vive en `CLAUDE.md` y `PLAN_MEJORAS.md` (raíz del repo) y en `docs/RUNBOOK.md`.
> No contiene claves ni datos de clientes.

---

## 0. Cómo quiero que me ayudes

- Respondé **en castellano rioplatense (voseo)**, directo, sin vueltas y sin exagerar. Si algo que se construyó antes estaba mal, decilo.
- No des por verdadero lo que no verificaste: separá "lo comprobé" de "lo supongo". Si algo se armó leyendo documentación y nunca se vio una respuesta real, avisalo.
- Antes de proponer cambios que toquen **plata, datos reales o aislamiento entre cuentas**, pedí confirmación y pensá en cómo probarlo contra una base real.
- Los textos de la app tienen que sonar **profesionales y seguros**: nada de frases que "protestan de más" ni comparaciones del tipo "no como otros" / "nunca hacemos X" cuando nadie preguntó.
- Para todo lo **fiscal o legal** (Monotributo, impuestos): avisá y sugerí; nunca digas "hacé esto" con seguridad total, recomendá confirmar con un contador.
- No agregues funciones por agregar: el dueño delegó las decisiones técnicas y de UX **para pulir**, no para sumar. Lo prioritario es llevar cada pantalla a nivel "listo para vender".
- Calibrá el esfuerzo al riesgo: un cambio de texto no necesita una batería de pruebas; algo que toca plata o RLS sí.

---

## 1. Qué es CoreLux

**CoreLux** es una app web (SaaS multi-tenant) de gestión para **vendedores de Mercado Libre de Argentina**. Se conecta a la cuenta de MeLi del vendedor (OAuth), sincroniza sus publicaciones y ventas y le
muestra, en castellano claro y con la menor fricción posible: **cuánta plata gana de verdad, qué tiene que hacer hoy, qué stock repone, a qué precio vender y cómo van sus publicaciones**.

- Nació como "Santi Mens", una app single-tenant (SQLite) para un negocio de **indumentaria**; esa carpeta original sigue existiendo aparte y **no se toca**. CoreLux vive en `CoreLux-SaaS`.
- Objetivo comercial: venderla por suscripción a otros vendedores de MeLi (plan base ~$40.000 ARS/mes, plan Elite ~$99.000, prueba de 14 días). **Hoy está en "beta gratuita"**: no hay cobro (ver §10).
- **Es un producto general**: lo usan vendedores de *todos los rubros* (no solo ropa). Por eso no se escribe lógica ni texto específico de indumentaria ni de una región (ver "capacidades" y "vocabulario" en §6).
- Producción real: https://corelux.app (Fly.io). El dueño es Diego; también la usan familiares suyos (cuentas de cortesía en Plan Elite gratis, sin cobro).

### Propuesta de valor (lo que diferencia al producto)
1. **Ganancia Neta Real** que coincide con lo que Mercado Pago realmente deposita (se verificó contra el depósito real al 0,31% en 1.062 ventas).
2. Una app que dice **qué hacer** ("cómo voy → qué hago → números → detalle"), no un tablero de ceros.
3. Cubre el día a día completo: despacho, preguntas, reclamos, stock, precios con piso de rentabilidad, calidad de publicaciones, impuestos (Monotributo), cobros.

---

## 2. Stack y arquitectura

| Capa | Qué se usa | Notas que importan |
|---|---|---|
| Backend | **Flask 3.1** (un `app.py` grande, ~3.900 líneas, más ~85 módulos `.py` en la raíz) | Servidor: gunicorn con workers **gevent** en Linux (Waitress en Windows local). |
| Base | **PostgreSQL en Supabase** (región São Paulo) | **psycopg 3** (`psycopg[binary,pool]`), *no* psycopg2 (el dueño usa Python 3.14). Pool `ConnectionPool` de `psycopg_pool`. |
| Multi-tenant | **Row Level Security** real de Postgres | No es un `WHERE cuenta_id = X` a mano: una política lee `current_setting('app.usuario_actual')` y `app.cuenta_actual`. |
| Hosting | **Fly.io**, app `corecore`, región `gru`, 2 máquinas × 2 workers | Dominio `corelux.app` (Cloudflare, proxied). **No hay Redis en producción** (sí en la PC del dueño). |
| Frontend | **Jinja2 + JS vanilla** (sin framework, sin bundler) + Chart.js servido local | Todo estático en `static/` (CSS: `style.css`, `shell.css`, `ux.css`; JS: `global.js`, `ux.js`, `tablas.js`). Fuentes e librerías **auto-hospedadas** (no hay terceros: lo exige un test + CSP). |
| Segundo plano | `app._en_segundo_plano(fn, *args)` = un hilo. **APScheduler** corre en un proceso con *advisory lock* de Postgres (uno solo ejecuta los trabajos). | Celery se eliminó. No volver a llamar `.delay()`. |
| IA | Cualquier proveedor compatible con *Chat Completions* de OpenAI (hoy DeepSeek `deepseek-flash`) | Coach de Logros, Costos por chat, optimizar título, etc. `deepseek-flash` **razona**: con `max_tokens` chico se quedaba sin presupuesto; `ia_asistente.parametros_extra()` lo apaga. |
| Observabilidad | Sentry (si hay DSN), `/healthz` y `/healthz/db`, panel `/admin/salud` | |
| Pagos | **Mercado Pago: NO implementado todavía** | `config.PAGOS_HABILITADOS = bool(MP_ACCESS_TOKEN)`. |

### Los dos canales de conexión a la base — no mezclar
- `db.conexion_usuario(usuario_id, cuenta_id)`: uso normal, **con RLS**. Hace `set_config('app.usuario_actual', …, true)` — el `true` (variable por *transacción*, no por sesión) es intencional porque el pooler de Supabase no preserva variables de sesión de forma confiable. Costó un bug real en producción.
- `db.conexion_admin()`: **bypassea RLS**. Solo para `token_manager.py` (tabla `meli_tokens`, que bloquea todo acceso al rol normal: ni el propio usuario puede leer sus tokens crudos) y una lista corta permitida por un test.
- **Límite de conexiones**: el pooler de Supabase da **15 conexiones de sesión para todo el proyecto**. Cada worker de cada máquina tiene su pool: `máquinas × workers × DB_POOL_MAX ≤ 12` (hoy 2×2×3). Si se agregan máquinas/workers hay que bajar `DB_POOL_MAX`.

### Aislamiento por cuenta (la clase de bug más cara del proyecto)
Casi todos los ~12 bugs graves encontrados fueron **estado en memoria compartido entre todas las cuentas** (cachés a nivel de módulo, un lock único para todo el proceso, etc.): invisibles con un usuario, reales con dos.
Regla: cualquier dict/variable de módulo que guarde algo "para no repetir la consulta" es sospechoso — preguntate si está acotado por `cuenta_id`. Hoy se prefiere `cache_db.py` (tabla `cache_valores`, compartida y por cuenta) y `cache.leer()/guardar()` (que nunca lanzan, funcionan sin Redis).
Además **toda tabla con `cuenta_id` filtra también por la cuenta activa** (`app.cuenta_actual`, migración 0010); un test (`test_rls_cuenta_activa.py`) lo exige. Excepciones por diseño: `alertas_usuario`, `auditoria`, `feedback`, `meli_tokens` (son de la persona).

---

## 3. Modelo de datos (conceptos, no el esquema completo)

- **`usuarios`** (la persona; plan, email, prueba) → **`cuentas_meli`** (una o más cuentas de Mercado Libre; el plan Elite permite varias, con selector en el menú). Guarda `capacidades`, `margen_minimo`, `flex_umbrales`, `ultima_sincronizacion_ventas`, etc.
- **`meli_tokens`**: tokens OAuth cifrados (Fernet; clave rotable). Solo accesible por la conexión admin.
- **`productos_padre`** (la publicación) y **`productos_variantes`** (talle/color o variante). Un **"modelo"** es la agrupación de varias publicaciones por título limpio (`utils.limpiar_titulo_modelo`) — *los rankings y consolidados son siempre por modelo, nunca por publicación o talle*. `productos_padre.family_id` es la clave de modelo que no depende del título.
- **`ventas`** (una fila por ítem vendido): precio, `cargo_venta` (comisión + financiación + cupones del vendedor), `costo_envio` (real), `costo_flex`, `retenciones`, `neto_recibido`, `fecha_liberacion`, `monto_liberacion`, `hora_normalizada`, etc. `ventas_retiradas` archiva (reversible) las canceladas/reembolsadas.
- Posventa: `incidencias_posventa` (reclamos/devoluciones, con `afecta_reputacion` y `monto_retenido`), `preguntas_pendientes`.
- Costos: `gastos_operativos` (recurrentes, con prorrateo por día), costo de fabricación por publicación/grupo, `proveedores`.
- Otros: `historial_precios`, `historial_promociones`, `competidores_*`, `tendencias_*`, `logros_historial`, `alertas_usuario`, `navegacion_visitas` (alimenta el badge "MÁS USADO"), `auditoria` (solo INSERT/SELECT), `feedback`, `cache_valores`, `referrals`.
- Migraciones: `migrations/` (36 archivos), **aditivas e idempotentes**. En cada deploy corre `python migrate.py` como `release_command` de Fly (si falla, el deploy se frena). Verificar con `migrate.py --status` antes de asumir cuál es la última aplicada.

---

## 4. Reglas de negocio que NUNCA se rompen

1. **Ganancia Neta Real = Facturación − Cargos MeLi − Envíos − Publicidad − Costo de fabricación.**
2. Los consolidados por modelo (agrupando talles/publicaciones) usan siempre **promedio ponderado real** (total $ ÷ unidades), nunca promedio simple.
3. **FULL es de solo lectura de stock** (no se edita desde acá).
4. **Confirmación explícita antes de cualquier acción que modifique datos reales o toque plata**, mostrando antes/después (`confirmarDecision(...)`, modal que devuelve una Promesa; no `confirm()`).
5. Todo lo que cambia estado es **POST** (anti-CSRF por `Sec-Fetch-Site`/`Origin`); nunca una acción que escribe en un GET.
6. Las **retenciones** (IIBB, SIRTAC) se muestran aparte y **no restan** de la ganancia (son pago anticipado de impuestos).
7. Un reclamo solo es "grave" si **afecta la reputación** según MeLi (`utils.SQL_RECLAMO_AFECTA`); el resto se muestra como "por gestionar, sin impacto en tu reputación".
8. Si el costo de fabricación está en $0 la "ganancia" queda inflada: las pantallas lo avisan y el hero no se pinta de verde.

---

## 5. Sincronización con Mercado Libre

- `sincronizador.py`: catálogo (publicaciones/variantes). `ventas_sync.py`: **órdenes reales** desde `/orders/search`, incremental (guarda `ultima_sincronizacion_ventas`, con 2 h de colchón). `sincronizar_todo(usuario_id, cuenta_id)` orquesta y marca `sincronizacion_inicial_completa`.
- Se dispara solo al conectar la cuenta (hilo en `/callback`) y luego **cada 4 minutos para todas las cuentas activas** (APScheduler). Hay **webhooks** (`/notificaciones_meli`, `/webhook`) que juntan ráfagas (`antirrebote.py`, 1 sync por cuenta cada 15 s); el webhook responde en ~ms porque MeLi deja de enviar si tarda.
- Costo de régimen medido: ~19 llamadas a MeLi por ciclo y cuenta (`medir_sync.py`). No volver a pedir en cada ciclo lo que casi no cambia (stock de convivencia, impacto en reputación, dinero retenido usan `cache_db`).
- Enriquecimiento gradual (`enriquecimiento.py`): calidad, visitas, stock FULL no disponible, precio para ganar el catálogo, opiniones. Las pantallas **leen de la base, nunca esperan a la API**.
- **Hora de las ventas**: MeLi manda `…-04:00` aunque Argentina es UTC−3. Se convierte al ingresar (`ventas_sync._fecha_hora_argentina`). Para todo lo que dependa de la hora usar `utils.sql_momento_argentina()`; no sumar "+1 hora" a mano.
- **Costo real de envío y cargos**: `GET /shipments/{id}/costs` (`senders[0].cost`), repartido entre filas que comparten envío; cargos del pago vía `https://api.mercadopago.com/v1/payments/{id}` (`charges_details`).
- **Flex**: MeLi reporta envío 0 y el costo lo cobra la logística propia por zona; las zonas las define MeLi (`/flex/sites/MLA/users/{id}/subscriptions/v1`, *sin* `/shipping/`). El usuario carga "umbrales" (precio + zonas) y MeLi reintegra el 10% (`REINTEGRO_MELI`). Hoy solo ubica destinos en AMBA.

### Hechos de la API de MeLi verificados contra datos reales
- `GET /items?ids=` admite **máximo 20 ids** (antes se pedían 50 → 400 silencioso → no se actualizaba nada).
- `available_quantity` de las publicaciones "de convivencia" es el stock de FULL, no el propio.
- `seller_reputation.transactions.ratings` llega como "100 % neutral" = **MeLi ya no informa calificaciones**: se trata como "sin dato".
- `max_title_length` de la categoría es 60 pero los títulos reales miden 62–113: no existe un "MeLi trunca a 60".
- MeLi cerró (403) `/sites/{site}/search`, `/items/{id}` de terceros y `/highlights`: Tendencias y Competencia se rehicieron sobre `/products/search`, `/products/{id}/items`, `/categories`, `/users`.
- `GET /trends/MLA/{categoría raíz}` trae ruido ajeno al rubro; se usan las categorías hoja de la cuenta.
- Las opiniones se comparten por `family_id` (todos los talles de un modelo): se consulta una por familia.
- `financing_add_on_fee` (cuotas) se cobra **por publicación, en cada venta, aunque el comprador pague de contado**.
- MeLi no deja cambiar el título de una publicación con ventas ni reabrir una cerrada (`closed` es irreversible); el stock se escribe **absoluto (PUT)**, nunca incremental.

---

## 6. Producto: pantallas y navegación

Menú lateral de **7 secciones** (fuente única: `nav_config.GRUPOS_NAV`); dentro de cada una, las pantallas salen como **pestañas**. En celular hay barra inferior. Para agregar una pantalla: sumarla ahí.

| Sección | Pantallas |
|---|---|
| Inicio | Dashboard |
| Día a día | Despacho · Preguntas · Pendientes (Logros) · Reputación |
| Ventas y ganancia | **Ganancia Real** · Facturación · Cobros · Ventas fuera de MeLi · Reporte Fiscal · Monotributo |
| Precios y costos | Costos · Precios · Calculadora MeLi · Historial de precios |
| Stock | Stock · Stock Masivo |
| Publicaciones | Calidad · Opiniones · Embudo de conversión |
| Crecimiento | Promociones · Publicidad (solo si hay Ads) · Tendencias · Competencia (solo si hay catálogo) |

Más: onboarding de 3 preguntas + tutorial guiado, `/cuenta` (preferencias, "descargar mis datos"), `/admin` (solo el dueño: usuarios, días de prueba, salud del sistema), Ctrl+K (buscador global), **campana de avisos** (reclamos, preguntas sin responder, publicaciones sin stock, devoluciones; `dashboard.armar_avisos`).

### Mecanismos transversales
- **Capacidades por cuenta** (`capacidades.py`): `ads / flex / full / catalogo` = True/False/ausente. **Solo un `False` confirmado esconde** una pantalla o sección (ausente nunca esconde). Disponible en templates como `capacidades` y en JS como `window.CAPACIDADES`.
- **Vocabulario** (`utils.vocabulario`): "talle" si la cuenta tiene talles reales, "variante" si no. Los textos usan `vocab.v1 / vocab.vN`.
- **Talle centralizado**: `utils.extraer_talle(titulo, talle_real)` es la ÚNICA forma de obtenerlo (un regex repetido en 8 módulos tomaba cualquier número del título).
- **Tablas ordenables**: `static/js/tablas.js` (`<table data-ordenable>` + `<th data-orden="num|texto">`); en celular, selector "Ordenar por". Títulos largos en una línea con `titulo-1l` + `title`.
- **Plata sin centavos** en pantalla (`|plata`), fechas para personas (`|fecha`, `rango_fechas`, `cuando_corto`), plurales (`|plural`, nunca "venta(s)").

---

## 7. Diseño visual (identidad vigente — no cambiar sin confirmación explícita)

- **Design System v2**: fondo grafito plano, tarjetas de borde casi invisible; **violeta** (`--accent-primary` `#8b5cf6`) = identidad y color de acción (botones primarios, estados activos); **dorado** reservado solo para logo, badges "más usado" y momentos de ganancia puntual (nunca botones). La estética anterior (Tron/vaporwave) **ya no vale**.
- Componentes de foco en `static/css/ux.css` con un solo mecanismo de color (`--ux-c`): `ux-ok` verde (plata/todo bien) · `ux-danger` rojo (urgente/pierde plata) · `ux-warn` naranja · `ux-info` celeste · `ux-accion` violeta · `ux-gold` · `ux-neutral`. Macros Jinja en `templates/_ux.html` (`banner`, `kpi`, `vacio`, `seccion`) y `static/js/ux.js` para pantallas armadas con fetch.
- Regla de cada pantalla: **cómo voy → qué hago → números → detalle plegado**. Un botón primario por pantalla; historial y tablas largas al final.
- **Todo texto externo (MeLi, base, usuario) se escapa** (autoescape / `UX.esc` / `textContent`); `|safe` solo para HTML armado por nosotros.
- Tema claro y oscuro; cada gráfico lee los colores de los tokens. Mobile-first en lo importante (barra inferior, tablas → tarjetas).

---

## 8. Seguridad y operación

- `seguridad.py`: anti-CSRF, cookie HttpOnly/SameSite=Lax/Secure, cabeceras, **CSP** (todavía con `'unsafe-inline'` porque quedan `onclick` en el HTML), páginas de error (JSON en `/api/*`), `/healthz`.
- `limitador.py` (429 por ventana deslizante, por proceso) · `auditoria.py` (`@auditar("accion")` debajo de `@login_requerido` en toda ruta que cambie datos reales o plata; un test lo exige) · claves rotables sin cortar a nadie (`TOKEN_ENCRYPTION_KEY`, `FLASK_SECRET_KEY` + `_ANTERIOR`).
- Respaldos (`respaldo.py`): fuera del proyecto, cifrados (`RESPALDO_CLAVE`). **Falta** programar la tarea semanal (es del dueño).
- Dependencias con rangos acotados, Dependabot y `pip-audit` en CI.

---

## 9. Cómo se trabaja (proceso)

- Todo corre en un **venv** (`venv\Scripts\...` en Windows). Python 3.14 local, 3.13 en producción (Docker `python:3.13-slim`). No asumas que un `pip install` global sirve.
- **Pruebas**: `pytest` (hoy **512 pasan**, `ruff` limpio). Incluyen tests de guarda que fallan si se rompe un patrón: fechas, cachés, `conexion_admin` solo en la lista permitida, `cuenta_id` en las conexiones, filtros de plantillas, `type=` en botones, navegación, imagen Docker sin vistas previas, dependencias de producción, RLS por cuenta activa, sintaxis/arranque de JS (con `node`), recursos locales y CSP. Algunas se ejecutan contra la **base real** (`predeploy.py` falla si algo se omite).
- ⚠️ Al correr pruebas y commitear en el mismo comando: **nunca con `;` ni detrás de un pipe** (esconde el código de salida; ya se subió un commit con pruebas en rojo).
- ⚠️ **Probar siempre también SIN Redis**: la PC del dueño tiene Redis y Fly no.
- ⚠️ **JavaScript sin compilador**: borrar una función que todavía se llama desde el arranque de `global.js` rompe la inicialización de TODAS las pantallas (pasó con `cargarHud()`). Antes de dar un cambio de JS por bueno, mirar la consola del navegador.
- ⚠️ Una captura tomada a mitad de una animación muestra elementos a medio dibujar: medir con el DOM antes de reportar un bug visual.
- **Deploy: SIEMPRE `python desplegar.py`** desde `CoreLux-SaaS`: verifica carpeta/rama/git limpio, corre `predeploy.py`, despliega con `--build-arg GIT_SHA`, confirma que `/healthz` informa esa versión, prueba rutas clave y **vuelve solo a la última release buena** si producción queda caída. La imagen se niega a construirse si falta una dependencia (`verificar_dependencias.py`; el 2026-10-06 faltaba `packaging` y producción estuvo caída). Un `fly deploy` a mano ya dejó código viejo en producción.
- Vistas previas con datos reales (`static/_prev`) se borran antes de commitear/desplegar. Un git "sucio" (incluidos archivos sin seguimiento) frena el deploy.
- Se avanza por tandas pequeñas, cada una commiteada y verificada; el plan vivo está en `PLAN_MEJORAS.md` (243 ítems con estado). `cosas.txt` tiene los bugs reportados por el dueño usando la app real.

---

## 10. Estado actual y lo que falta

### Hecho recientemente (octubre 2026)
Costos reales de envío/cargos conciliados con el depósito · reclamos que afectan reputación · opiniones por familia · cobros y dinero retenido · Monotributo · Costos por chat con confirmación · Flex por zonas · Ganancia Real con conciliación · normalización de horas · menú de 7 secciones + barra inferior · panel de edición de publicación y stock absoluto · modo beta · CSP + recursos locales · auditoría de 100 puntos · panel `/admin` · deploy seguro con rollback automático · **campana de avisos** · **Stock** (aviso sin parpadeo, filtros "Se agota pronto"/"Con stock en FULL", columna "Alcanza para") · **tablas ordenables** y títulos de una línea (Stock, Ganancia Real, Calidad).

### Pendiente / abierto
- **Cobro por Mercado Pago** (planes, suscripción, excluir las cuentas de cortesía del cobro). Hoy beta gratuita.
- Aplicar el ordenamiento al resto de las tablas · **ficha única de publicación** (ítem 219 del plan) · sacar los `onclick` para quitar `'unsafe-inline'` del CSP · mails/alertas (falta elegir proveedor) · onboarding que use las respuestas · landing con prueba/demo · métricas de admin.
- Del lado del dueño: programar el respaldo semanal (`RESPALDO_CLAVE`), monitor de uptime sobre `/healthz`, tildar los temas de webhook y la Notification URL (`https://corelux.app/notificaciones_meli`) en MeLi Developers.
- ⚠️ **Construido sin verificar contra datos reales**: multi-cuenta Elite de punta a punta (se trazó contra el patrón probado, nunca se corrió en vivo con una segunda cuenta), panel de catálogo "precio para ganar" (contra documentación; la cuenta de prueba no tiene catálogo), reconciliación del costo Flex (para 09/09–01/10 MargenFull muestra $378.250 y esta lógica $326.110 sobre 39 envíos; no se pudo reconciliar), y el caso Flex de productos < $33.000 (ahí paga el comprador).

### No existe todavía (no lo asumas)
Puente de WhatsApp · envío de mensajes a compradores desde la app (se responde en MeLi) · mails/notificaciones del navegador · cobro por Mercado Pago · auditoría automática de devoluciones más allá de `ventas_sync` · otros marketplaces (Tiendanube/Shopify) · inteligencia competitiva cruzando mercados (Amazon/Alibaba/Latam) y predicción de tendencias: es una conversación de arquitectura aparte, sin arrancar.

---

## 11. Qué te puedo pedir con este contexto

- Revisar una decisión de producto o de arquitectura (por ejemplo: cómo cobrar con Mercado Pago sin tocar a las cuentas de cortesía, cómo escalar el sync más allá del tope del pooler, cómo diseñar la ficha única de publicación).
- Criticar el copy de una pantalla según el tono de §0, o proponer mejoras de UX dentro del Design System vigente.
- Armar casos de prueba para algo que toca plata, RLS o la sincronización.
- Planificar la visión de largo plazo (inteligencia competitiva, otros marketplaces) **sin romper** las reglas de §4.

Si te falta un dato, preguntá antes de inventarlo.

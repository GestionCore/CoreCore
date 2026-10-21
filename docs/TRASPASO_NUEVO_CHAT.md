# Traspaso para un chat nuevo (2026-10-21)

> Leer en este orden: este archivo → `CLAUDE.md` (se carga solo) → `PENDIENTES.md` (§0f es lo último) → `docs/TUS_PENDIENTES.md` (lo que le toca al dueño, paso a paso).
> La memoria del proyecto (`~/.claude/projects/…/memory/MEMORY.md`) también se carga sola.

## 1. Dónde estamos
- Repo `main` sincronizado con GitHub. Último código: el commit de la auditoría de diseño (después de `3bb9e24`).
- **Producción corre `f126954`** (el dueño la desplegó con `python desplegar.py` y `/healthz` informó `f1269545cbaa`). Subido a git y **NO desplegado**: `f33af4d`, `b471100`, `3bb9e24`, `428385e` y lo de esta noche (§3b). No hay migraciones nuevas. Lo despliega el dueño con `python desplegar.py` desde `CoreLux-SaaS`.
- 1.740 pruebas pasan (con y sin Redis). Ruff limpio.
- El dueño es **Diego** (usuario 3, cuentas de Mercado Libre `2` = DIEGOARIELSANTIAGO y `7` = NOENOEINDUMENTARIA, plan Elite). Mercado Pago corre con credenciales de PRODUCCIÓN y un precio de prueba de $100 para UN mail (`MP_EMAIL_DE_PRUEBA` + `MP_PRECIO_DE_PRUEBA`), sin cobro real todavía.

## 2. Cómo trabaja el dueño (no negociable)
- Explicaciones muy simples y paso a paso para lo que le toca a él. Directo, sin introducciones largas.
- «Modo pulir»: pulir lo que existe antes de inventar funciones, y **decirle con honestidad cuándo ya estamos bien**.
- Verificar CADA afirmación contra código, base real o navegador antes de decirla o tocarla (~25 % de lo que traen las auditorías externas es falso). La API real manda sobre la teoría.
- Confirmación explícita antes de tocar datos reales o plata. Nunca pegar claves ni tokens en el chat (él las carga con `fly secrets set`).
- La identidad visual (grafito + violeta + dorado) no cambia sin permiso. Tono profesional pero con voseo.
- Desplegar SOLO con `python desplegar.py`, lo corre él, y no se editan archivos del repo mientras construye la imagen.
- La IA del asistente: solo Mercado Libre y la cuenta que consulta, nada más (3 capas, ver CLAUDE.md «Asistente de IA»).
- Flex: el PRECIO de la logística lo carga la persona a mano; el programa nunca lo autocompleta ni registra fechas de pago a la logística.

## 3. Lo hecho en esta tanda (commit `4f5db00`)
Detalle en `PENDIENTES.md` §0f. Resumen:
1. Chat de IA por cuenta (`corelux_chat_v1_<cuenta>` en `sessionStorage`) + 409 `recargar` del servidor si la cuenta activa cambió en otra pestaña + «Consultando: <cuenta>» en el encabezado. El servidor siempre usó la cuenta correcta; fallaba el navegador.
2. Asistente con 30 herramientas: nueva `tendencias` (solo lectura), `mercado` y `competencia` más ricas; reglas 12 y 13 del prompt (afirmar lo que dicen los datos, un solo límite en una frase, consultar mercado + tendencias + competencia juntas).
3. Despacho: «Traer ventas nuevas» → «Actualizar». Dólar: «Dólar manual» → «Cambiar valor». Preferencias: «Estás en esta cuenta» y barrido de frases coloquiales.
4. Ganancia Real ya no abre bajada hasta «Evolución mensual» (`ux.js`: las pestañas usaban `scrollIntoView`).
5. Tope de cuentas `config.MAX_CUENTAS_ELITE = 2` hecho cumplir en el servidor (no existía) y sin botón «Agregar otra cuenta» cuando ya están. Bug 404 del botón «Ver esta cuenta» arreglado.

## 3b. Lo hecho la noche del 2026-10-21 (el dueño dormía y pidió una sesión larga sin preguntas)
- Dos auditorías de 100 puntos con evidencia y estado: `docs/AUDITORIA_TECNICA_100.md` y `docs/AUDITORIA_DISENO_100.md`. Cada una abre con cómo se verificó, qué se descartó y «si solo se hacen 10». Son propuestas: el dueño elige.
- Arreglos reales (con prueba): ventanas de tiempo completas (alerta de caída, salud, promociones, visitas, proyección del mes), no crear una 2.ª suscripción si la vieja no se cancela, órdenes rechazadas ya no adelantan la marca del sync, agregar gasto con montos argentinos, `parsear_monto("1e3")`, Sentry con usuario/versión, cachés de Ganancia Real (de 20 s a 0,4 s en evolución mensual), herramienta `despacho` del asistente (31.ª), modo privacidad 57/57, «Ventas hoy» vs. ayer a la misma hora, Calidad sin «100/100» falso, Planes con la cuenta en la barra, confirmaciones violetas (rojo solo si destruye), chips de celular de 44 px, código de incidente en los errores, movimiento reducido también en JavaScript, miniaturas guardadas con https.
- Las dos decisiones de identidad visual que necesitan al dueño: D15 (violeta más oscuro solo para fondos con texto blanco) y D46 (dorado de la marca en tema claro).

## 4. Lo que falta
**Del dueño** (detalle paso a paso en `docs/TUS_PENDIENTES.md`)
- Desplegar. Cargar los 3 precios Flex (Costos → Entrega Flex → Detectar → precios → Guardar → confirmar la vista previa): hoy su ganancia neta real sale inflada (~190 envíos Flex sin costo). Cargar el costo de fabricación de 17 de 71 publicaciones de la cuenta 7.
- `soporte@corelux.app` (Cloudflare Email Routing → Gmail). Prueba real de Mercado Pago con la hermana (cobrador `manuzapalloo@gmail.com`; su mail de Mercado Libre = `MP_EMAIL_DE_PRUEBA`; luego cancelar, reembolsar y `fly secrets unset MP_EMAIL_DE_PRUEBA MP_PRECIO_DE_PRUEBA -a corecore`). Mails con Resend (después de `soporte@`). Respaldo semanal (`respaldo.py`, `RESPALDO_CLAVE`). `CSP_MODO=estricta` tras una semana de logs sin `[CSP]`.
- En Mercado Libre Developers confirmar los temas de notificaciones (items, orders_v2, shipments, questions, claims/post_purchase, items_prices; URL `https://corelux.app/notificaciones_meli`): en los logs solo se vieron shipments y ofertas.
- Revisión legal de Términos y Privacidad (incluye WhatsApp si se hace). Confirmar precios $40.000 / $99.000 antes de la primera suscripción real. Probar con un vendedor real de OTRO rubro (el «sirve para cualquier rubro» no está probado con una cuenta real). Ver el ícono instalado en el celular. Condición fiscal en «Mi cuenta» y revisar las escalas de Monotributo (cambian ~2 veces por año).
- **Decidir WhatsApp** (`docs/PLAN_WHATSAPP.md`): API oficial o no · incluido en Elite o extra pago · arrancar la verificación de Meta Business · qué avisos van por defecto.

**Míos**
- WhatsApp cuando decida: Fase 1 avisos (vinculación por OTP, webhook firmado, plantillas, topes) → Fase 2 IA por WhatsApp → Fase 3 acciones con confirmación.
- Reconciliar MargenFull ($378.250) contra Flex ($326.110) con el dato por envío nuevo.
- Pulido: Ganancia Real es una página de ~17.000 px (aliviar), velocidad de `/dia`, Stock con cuentas enormes, ítems de `PLAN_UX_200.md` (6, 99, 91, 163, 79/141, 80, 86, 33, 42, 46, 194, 20/25/30, 38, 135), sacar los `style=` de las plantillas (120), eliminar las columnas `talle`/`color`, tablas ordenables que faltan, decisión de costo por variación dentro de una publicación, «pedir seguimiento» de categorías desde la pantalla Mercado.

## 5. Trampas de este entorno
- El `Bash` se come `\n` en heredocs largos: escribir con Write/Edit y correr el script. En Windows, `MSYS_NO_PATHCONV=1` si hace falta.
- Nunca `| tail` ni `;` escondiendo el código de salida de pytest/ruff antes de commitear: correr, mirar `exit` y recién ahí commitear.
- Importar `app` en un script suelto arranca el scheduler: antes poner `import scheduler; scheduler.iniciar_scheduler = lambda: None`.
- Servidor de verificación en el navegador: `servir_verificacion2.py` en el scratchpad de la sesión anterior (`C:\Users\clona\AppData\Local\Temp\claude\…\scratchpad\`); si no está, se rearma (monkeypatch del token y de Mercado Libre, sesión forzada a la cuenta 2, puerto 5056, scheduler apagado). Usa la base de PRODUCCIÓN: **nunca enviar formularios**. Hay que PARARLO antes de correr `pytest` (el pooler da 15 conexiones y se agota) y reiniciarlo tras editar un `.html` (cachea plantillas).
- Con el panel del navegador en segundo plano `innerHeight` es 0: para medir scroll/layout usar números del DOM, no capturas.
- Pruebas con base real: transacciones que no se confirman (`tests/test_cuenta_nueva.py`, `tests/test_multicuenta_real.py`). Para ver cuentas de OTRA persona hay que usar `db.conexion_admin()` (con RLS no se ven).
- Medir desde la PC engaña el rendimiento: mirar `fly logs -a corecore | grep "\[Lento\]"`.
- Pooler de Supabase: máquinas × workers × `DB_POOL_MAX` ≤ 12.

## 6. Primer mensaje para pegar en el chat nuevo
```
Retomamos CoreLux-SaaS. Leé docs/TRASPASO_NUEVO_CHAT.md, después PENDIENTES.md (§0f) y seguí desde ahí. Primero confirmame en 5 líneas qué entendiste del estado (qué está desplegado y qué no, y qué te toca a vos) y recién después arrancá con lo siguiente que corresponda. Si algo que te digo contradice el código, mostrame la evidencia antes de forzarlo.
```

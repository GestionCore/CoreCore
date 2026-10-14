# Tus pendientes, paso a paso

Hecho el 2026-10-14. Están en el orden en que conviene hacerlos. Cada uno dice cuánto tarda, qué hacer y **cómo saber que salió bien**.

**Regla de oro:** las claves y tokens (Mercado Pago, Resend, Sentry, Supabase) **nunca** se pegan en el chat ni en un mail: se cargan directo en Fly con el comando que figura abajo. Si algo falla, pegame solo el *mensaje de error*, sin claves.

| # | Qué | Tiempo | Por qué importa |
|---|---|---|---|
| 0 | Desplegar lo nuevo | 5 min | Todo lo hecho hoy (IA nueva, celular, accesibilidad) todavía no está en corelux.app |
| 1 | Costo de entrega Flex | 10 min | Tu ganancia real hoy sale **inflada** (190 envíos sin costo) |
| 2 | Costos de fabricación que faltan | 5 min | Sin costo, la ganancia es mentira |
| 3 | Que exista `soporte@corelux.app` | 10 min | Está publicado en la web: si nadie lo recibe, un cliente se pierde |
| 4 | Cobro real con Mercado Pago | 45 min | Hoy nadie puede pagar de verdad |
| 5 | Mails automáticos (Resend) | 30 min | Avisos de cobro y de prueba que vence |
| 6 | Aviso si la página se cae | 10 min | Enterarte antes que un cliente |
| 7 | Errores por mail (Sentry) | 15 min | Saber qué falla sin mirar logs |
| 8 | Avisos en vivo de Mercado Libre | 10 min | Que las ventas y reclamos entren al instante |
| 9 | Respaldo semanal | 10 min | Tener copia de los datos fuera de la nube |
| 10 | Seguridad estricta del navegador | 5 min | Se hace después de una semana de uso |
| 11 | Antes de vender | — | Abogado, precios y un vendedor de otro rubro |

---

## 0. Desplegar lo nuevo (5 minutos)

Hay 16 cambios hechos y subidos a git que **todavía no están en producción**. No hay migraciones nuevas (la última sigue siendo la 0050).

1. Abrí una terminal en la carpeta del proyecto (`CoreLux-SaaS`, la de siempre).
2. Escribí:

```bash
python desplegar.py
```

3. Tarda unos 5 minutos: primero corre todas las pruebas (si algo falla, **no sube nada**) y después despliega.
4. **Cómo sé que salió bien:** al final dice la versión nueva. Abrí `https://corelux.app/healthz` (tiene que decir `ok` y mostrar esa versión), entrá a la página y abrí el chat con una pregunta, por ejemplo «¿cómo voy?».
5. **Si falla:** el script vuelve solo a la versión anterior. Pegame el mensaje.

Lo que se activa con este deploy: la IA con 29 herramientas y límite de temas, el contexto del negocio, Publicidad corregida (el presupuesto de campaña es diario), pantallas sin desborde en celulares de 320 px, campos con etiqueta para lectores de pantalla y la corrección de velocidad para cuentas con muchas ventas.

---

## 1. Cargar el costo de entrega Flex (10 minutos)

**El problema:** tenés 190 envíos Flex (61 en el último mes) sin costo de entrega. Mercado Libre informa ese costo como $0 porque lo cobra tu propia logística. Hasta que lo cargues, la «ganancia neta real» no lo descuenta y sale más alta que la verdadera.

1. Entrá a **Costos** y bajá a la sección **Entrega Flex**.
2. Cargá lo que te cobra tu logística según la zona (los «umbrales»: un precio y las zonas que cubre). Si no tenés la tarifa a mano, pedísela a quien hace tus entregas.
3. Te muestra una **vista previa**: cuántos envíos caen en cada precio y cuánto suman. Revisala.
4. Confirmá. (La app ya calcula sola el reintegro del 10 % de Mercado Libre.)
5. **Cómo sé que salió bien:** en **Ganancia Real** desaparece el aviso «N envíos Flex sin costo de entrega» y la ganancia baja a su valor real.

## 2. Cargar los costos de fabricación que faltan (5 minutos)

La cuenta **NOENOEINDUMENTARIA** tiene 17 de 71 publicaciones activas sin costo.

1. **Costos** → mirá el filtro/etiqueta «sin costo».
2. Cargá un costo por **modelo** (se aplica a todos sus talles) o por variante si cambia.
3. **Cómo sé que salió bien:** el aviso «al X % de lo que facturaste le falta el costo» desaparece de Ganancia Real y del Inicio.

## 3. Que `soporte@corelux.app` exista (10 minutos)

Esa dirección está escrita en la página principal, en la pantalla «sincronizando» y en los términos. Si el dominio no tiene casilla, los mails a esa dirección **rebotan**.

La opción más simple y gratis: reenviar a tu Gmail con Cloudflare.

1. Cloudflare → tu dominio **corelux.app** → **Email** → **Email Routing** → *Comenzar*.
2. Creá la dirección `soporte` y ponele de destino tu Gmail. Cloudflare te manda un mail de confirmación: aceptalo.
3. Dejá que Cloudflare agregue los registros DNS que pide (MX y SPF).
4. **Cómo sé que salió bien:** mandá un mail a `soporte@corelux.app` desde otra cuenta; tiene que llegarte a tu Gmail.

## 4. Cobro real con Mercado Pago (45 minutos)

**Estado hoy:** producción usa las credenciales de **prueba** de Mercado Pago. Nadie puede pagar de verdad. Tu usuario y los de tus padres son «cortesía»: nunca se les cobra.

**Primero decidí una cosa — ¿beta gratis o cobrar ya?**

- **Beta gratis con amigos primero** (recomendado si todavía no tenés clientes): sacá el token de prueba y la página pasa sola a «beta gratuita» (la prueba no bloquea a nadie y no se muestra nada de pagos):

```bash
fly secrets unset MP_ACCESS_TOKEN -a corecore
```

- **Cobrar ya:** seguí los pasos de abajo.

Pasos para el cobro real:

1. Mercado Pago → **Tus integraciones** (`mercadopago.com.ar/developers`) → tu aplicación → **Credenciales de producción**. Si te pide activarlas, completá los datos del negocio.
2. Copiá el **Access Token de producción** (empieza con `APP_USR-`).
3. En la misma aplicación → **Webhooks** → modo **producción**: URL `https://corelux.app/webhook/mercadopago` y el evento de **Planes y suscripciones**. Copiá la **clave secreta** que te muestra.
4. Cargá las dos cosas en Fly (se reinicia solo, no hace falta desplegar):

```bash
fly secrets set MP_ACCESS_TOKEN=PEGÁ_EL_TOKEN MP_WEBHOOK_SECRET=PEGÁ_LA_CLAVE -a corecore
```

5. **Probalo vos con plata real chica:** suscribite a un plan con una tarjeta tuya, mirá que el plan pase a activo, cancelalo desde CoreLux y comprobá en Mercado Pago que la suscripción se dio de baja. Después pedí el reembolso desde Mercado Pago.
6. Si algo se rompe: cancelá la suscripción desde el panel de Mercado Pago y poné el plan en «cancelado» desde `/admin`.

## 5. Mails automáticos con Resend (30 minutos)

Son 6 avisos del servicio (cobro pendiente, plan dado de baja, suscripción cancelada, plan cambiado, prueba por vencer, prueba vencida). Hoy está **apagado**.

1. Creá una cuenta en **resend.com** (el plan gratis alcanza al principio).
2. **Domains** → *Add Domain* → `corelux.app`. Te da unos registros DNS (SPF y DKIM).
3. Cargalos en Cloudflare: **DNS** → *Add record*, uno por uno, con la nube **gris** (sin proxy). Volvé a Resend y tocá **Verify**.
4. **API Keys** → *Create* (permiso solo para enviar) → copiá la clave.
5. Cargalo en Fly:

```bash
fly secrets set CORREO_PROVEEDOR=resend CORREO_API_KEY=PEGÁ_LA_CLAVE CORREO_REMITENTE="CoreLux <avisos@corelux.app>" CORREO_RESPONDER_A=soporte@corelux.app -a corecore
```

6. **Cómo sé que salió bien:** el manual (`docs/RUNBOOK.md`, §9b-2) tiene un comando para mandarte un mail de prueba con `fly ssh console`. Tiene que decir `enviado`.
7. Para apagarlo en segundos: `fly secrets unset CORREO_API_KEY -a corecore`.

## 6. Aviso si la página se cae (10 minutos)

1. Creá una cuenta gratis en **uptimerobot.com**.
2. *Add New Monitor* → tipo **HTTP(s)** → URL `https://corelux.app/healthz/db` → cada **5 minutos** → alerta a tu mail.
3. **Cómo sé que salió bien:** el monitor aparece en verde («Up»).

## 7. Errores por mail con Sentry (15 minutos)

1. Creá una cuenta gratis en **sentry.io** → *Create Project* → plataforma **Flask** (Python).
2. Copiá el **DSN** que te muestra (una URL larga).
3. Cargalo en Fly:

```bash
fly secrets set SENTRY_DSN=PEGÁ_EL_DSN -a corecore
```

4. **Cómo sé que salió bien:** en Sentry el proyecto deja de decir «esperando eventos» después de un rato de uso. Por defecto te avisa por mail de cada error nuevo.

## 8. Avisos en vivo de Mercado Libre (10 minutos)

La dirección ya está cargada (producción recibe avisos). Falta confirmar que estén **tildados los temas que la app usa**.

1. `developers.mercadolibre.com.ar` → **Mis aplicaciones** → tu aplicación → **Notificaciones**.
2. URL: `https://corelux.app/notificaciones_meli`.
3. Tildá: **Items**, **Orders** (órdenes), **Shipments** (envíos), **Questions** (preguntas), **Claims / Post-purchase** (reclamos) y **Items prices**. Los demás se ignoran sin problema.
4. **Cómo sé que salió bien:** dentro de unos minutos de actividad, `fly logs -a corecore | grep "\[Webhook\]"` muestra líneas con cada tema.

## 9. Respaldo semanal en tu PC (10 minutos)

1. Una sola vez, generá la clave del respaldo (en la carpeta del proyecto):

```bash
python respaldo.py --generar-clave
```

2. Guardá esa clave en tu gestor de contraseñas **y** en el archivo `.env` como `RESPALDO_CLAVE=...`. **Si la perdés, perdés el respaldo.**
3. Probalo: `python respaldo.py` → crea un archivo cifrado en `C:\Users\clona\CoreLux-respaldos`.
4. Para que se haga solo cada domingo a las 22:00, abrí el **Símbolo del sistema (cmd)** y pegá todo en una línea:

```
schtasks /Create /SC WEEKLY /D SUN /ST 22:00 /TN "CoreLux respaldo" /TR "\"C:\Users\clona\Desktop\Integrador MELI Alpha v0.0\Integrador\CoreLux-SaaS\venv\Scripts\python.exe\" \"C:\Users\clona\Desktop\Integrador MELI Alpha v0.0\Integrador\CoreLux-SaaS\respaldo.py\""
```

5. De vez en cuando copiá esa carpeta a un disco externo. Y confirmá en Supabase (**Database → Backups**) que sus respaldos diarios estén activos.

## 10. Seguridad estricta del navegador (5 minutos, después de una semana)

Hoy corre en «modo prueba»: la política estricta solo **avisa** lo que bloquearía.

1. Después de una semana de uso normal, mirá los avisos: `fly logs -a corecore | grep "\[CSP\]"`.
2. Si no hay avisos propios de tu página, activala:

```bash
fly secrets set CSP_MODO=estricta -a corecore
```

3. Si algo dejara de funcionar, esto lo deshace en segundos: `fly secrets set CSP_MODO=actual -a corecore`.

## 11. Antes de vender

- **Términos y privacidad:** que los revise un abogado (se ven en `/terminos` y `/privacidad`; el código está en `legal.py`). Es lo único de esta lista que no puedo reemplazar.
- **Precios:** confirmá los planes que figuran en `/planes` ($40.000 base y $99.000 elite).
- **Un vendedor de otro rubro:** la página dice que sirve para cualquier rubro. Está probado con datos sintéticos y con la API, **no con una cuenta real que no sea de indumentaria**. Conseguí a alguien que venda electrónica, hogar o repuestos para que conecte su cuenta y después me contás qué ve. Hasta entonces, evitá decirlo como algo ya probado en tus videos.
- **Una prueba del asistente antes de grabar:** probá en el chat «¿qué producto me deja más margen?», «¿mi publicidad me deja plata?» y «¿qué promoción me conviene para el Día de la Madre?». Si alguna respuesta te parece rara, anotá la pregunta y pasámela.

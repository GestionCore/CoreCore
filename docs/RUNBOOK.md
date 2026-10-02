# CoreLux — guía de operación

Qué hacer cuando algo pasa en producción (Fly.io, app `corecore`, región `gru`). Para el contexto de decisiones y reglas de negocio,
ver [`CLAUDE.md`](../CLAUDE.md); para arrancar el proyecto en local, el [`README.md`](../README.md).

## 1. Cómo saber si está sano

| Qué | Cómo |
|---|---|
| ¿La app responde? | `https://corelux.app/healthz` → `{"ok": true}` (no toca la base; es el chequeo de Fly cada 30 s) |
| ¿Llega a la base? | `https://corelux.app/healthz/db` → `{"ok": true, "db": true}`; `503` si la base no contesta. Ideal para un monitor externo (UptimeRobot o similar) |
| Estado de las máquinas | `fly status -a corecore` |
| Logs en vivo | `fly logs -a corecore` (buscar `❌`, `⚠️`, `Traceback`) |
| Errores agrupados | Sentry, si `SENTRY_DSN` está configurada (sin eso los errores solo quedan en los logs) |

## 2. Desplegar

```bash
python desplegar.py            # verifica carpeta y git, corre predeploy, despliega marcando la versión y confirma que producción la corre
```

(`fly deploy` a mano ya no hace falta: `desplegar.py` lo ejecuta y además comprueba el resultado. `/healthz` informa el commit desplegado.)

- Antes de arrancar la versión nueva corre `python migrate.py` (`release_command`): aplica las migraciones pendientes y, si una falla, **el
  deploy se frena** y la versión vieja sigue sirviendo. Las migraciones son idempotentes.
- **Antes de desplegar: `python predeploy.py`** (lint, pruebas, pruebas sin Redis, recorrido de las ~80 pantallas con las condiciones de Fly y migraciones
  pendientes; unos 2 minutos, no escribe nada). Con `--rapido` salta el recorrido. Existe porque Fly no tiene Redis y esta PC sí: un error que solo aparece
  sin Redis pasa todas las pruebas locales y rompería todas las páginas en producción.
- Hacer deploy solo con el CI en verde (`ruff` + `pytest`).
- Después del deploy: abrir `/healthz/db`, entrar a la app y mirar `fly logs -a corecore` un par de minutos.

**Volver atrás** si la versión nueva anda mal:

```bash
fly releases -a corecore            # lista de versiones
fly deploy -a corecore --image <imagen de la versión anterior que figura en fly releases>
```

Las migraciones solo agregan (tablas, columnas, índices): una versión vieja del código sigue funcionando sobre el esquema nuevo.

## 3. Migraciones

```bash
python migrate.py --status     # qué está aplicada y qué falta (contra la base real del .env)
python migrate.py              # aplica las pendientes
```

El número más alto en `migrations/` no siempre coincide con lo aplicado: mirar `--status` antes de asumir.

## 4. Secretos y rotación de claves

Los secretos viven en Fly, nunca en el repositorio: `fly secrets set NOMBRE=valor -a corecore` (reinicia las máquinas) y
`fly secrets list -a corecore`.

### Clave de cifrado de los tokens de Mercado Libre (`TOKEN_ENCRYPTION_KEY`)

Se puede cambiar **sin desconectar a nadie**:

1. Generar una nueva: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. `fly secrets set TOKEN_ENCRYPTION_KEY=<la nueva> TOKEN_ENCRYPTION_KEY_ANTERIOR=<la que estaba> -a corecore`. Desde ese momento todo lo nuevo
   se cifra con la nueva y lo viejo se sigue leyendo con la anterior.
3. Volver a cifrar lo guardado, con el `.env` local apuntando a la misma base y con las dos claves:
   `python rotar_clave.py` (vista previa: no modifica nada) y después `python rotar_clave.py --aplicar`.
4. Cuando la vista previa diga "con una clave anterior: 0": `fly secrets unset TOKEN_ENCRYPTION_KEY_ANTERIOR -a corecore`.

Si se pierde la clave sin haber dejado la anterior, los tokens no se pueden leer: cada cuenta tiene que volver a conectarse desde la app.

### Clave de la cookie de sesión (`FLASK_SECRET_KEY`)

Cambiarla sin más cierra la sesión de todos. Para que no pase: `fly secrets set FLASK_SECRET_KEY=<nueva> FLASK_SECRET_KEY_ANTERIOR=<la que estaba>`,
y a los 14 días (lo que dura una sesión) borrar la anterior.

### Credenciales de Mercado Libre, IA y Mercado Pago

`MELI_CLIENT_ID/SECRET`, `IA_API_KEY`, `MP_ACCESS_TOKEN`: se cambian con `fly secrets set`. Al cambiar el secreto de la aplicación de Mercado Libre,
los tokens ya emitidos siguen funcionando hasta que se refresquen.

## 5. Base de datos (Supabase)

- El pooler de **sesión** de Supabase admite **15 conexiones para todo el proyecto**. Cada proceso usa hasta `DB_POOL_MAX` (hoy 3):
  `máquinas × workers × DB_POOL_MAX` tiene que ser ≤ 12 (hoy 2 × 2 × 3 = 12), dejando 3 para migraciones, respaldos y consultas a mano.
  **Antes de agregar una máquina o un worker, bajar `DB_POOL_MAX` o subir el plan de Supabase.**
- Síntoma de que se acabaron: errores `EMAXCONNSESSION` en los logs y pantallas que no cargan. Primero: `fly status` (¿máquinas de más?), después
  revisar si hay sesiones colgadas en el panel de Supabase.
- `db.conexion_usuario(usuario_id, cuenta_id)` es el camino normal (con RLS). `db.conexion_admin()` salta RLS y solo se usa en `token_manager.py`,
  `/admin`, el borrado de cuenta, migraciones, respaldos y `rotar_clave.py`.

### Respaldo

```bash
python respaldo.py --generar-clave # una sola vez: guardar la clave en RESPALDO_CLAVE (.env) Y en el gestor de contraseñas
python respaldo.py                 # ~/CoreLux-respaldos/AAAAMMDD_HHMM.zip.cifrado (con RESPALDO_CLAVE; sin ella, .zip en claro y un aviso)
python respaldo.py --con-tokens    # incluye meli_tokens (ya cifrados con TOKEN_ENCRYPTION_KEY): guardarlo como un secreto
python respaldo.py --descifrar RUTA.zip.cifrado   # deja el .zip al lado para abrirlo
```

- Se guarda **fuera del proyecto** (`~/CoreLux-respaldos`, o `RESPALDOS_CARPETA`) y se niega a escribir adentro: el zip tiene los datos de todos los
  usuarios y ya llegó a una imagen de Docker una vez. Con clave, el zip en claro nunca se escribe a disco. Perder la clave = perder el respaldo.
- **Semanal automático en la PC del dueño** (Windows, el domingo a las 22:00; ajustar las rutas):
  `schtasks /Create /SC WEEKLY /D SUN /ST 22:00 /TN "CoreLux respaldo" /TR "C:\RUTA\CoreLux-SaaS\venv\Scripts\python.exe C:\RUTA\CoreLux-SaaS\respaldo.py"`
  (el `.env` se busca junto al script, no importa desde dónde corra la tarea). Copiar de vez en cuando la carpeta a un disco externo.
- Supabase hace además sus propios respaldos diarios (según el plan: confirmarlo en Dashboard → Database → Backups). Probar cada tanto que un respaldo abre y tiene filas.

## 6. Sincronización con Mercado Libre

- Cada cuenta se sincroniza cada 4 minutos y por webhook (`/notificaciones_meli`, con un antirrebote de 15 s por cuenta).
- Sin Redis (el caso actual en Fly) corre APScheduler dentro de un worker, que toma un *advisory lock* de Postgres; si ese worker cae, otro lo toma
  en menos de un minuto. El reparto lo hace un lock de Postgres: solo un proceso corre las tareas y los demás vigilan por si cae.
- **No aparecen ventas nuevas**: ver en los logs `[VentasSync]` y `[Sincronizador]` de esa cuenta. Si dice `CuentaDesconectada`, el usuario revocó
  el permiso o cambió la clave de Mercado Libre: tiene que volver a conectar (`/reconectar`).
- Forzar un sync de una cuenta desde una consola con el `.env` local: `python -c "import sincronizador; sincronizador.sincronizar_todo(<usuario_id>, <cuenta_id>)"`.
- Mercado Libre limita `GET /items?ids=` a 20 ids; los datos de facturación (`/billing/.../details`) devuelven 429 rápido: usar el resumen cacheado.

## 7. Usuarios y cuentas

- **Eliminar una cuenta**: la persona lo hace sola desde *Eliminar mi cuenta* (`/cuenta/eliminar`): cancela la suscripción y borra todo en cascada.
- **Cambiar un plan a mano** (por ejemplo, cortesía): desde `/admin` (solo `ADMIN_EMAIL`). Las cuentas de cortesía no tienen suscripción de Mercado Pago:
  excluirlas de cualquier proceso de cobro.
- **Registro de actividad**: `/cuenta/actividad` muestra, por usuario, quién cambió qué (precios, stock, costos, planes…). La tabla `auditoria` es de solo
  agregar para la app.

## 8. Límites de pedidos

`limitador.py` (la IP del visitante sale de `CF-Connecting-IP`: el dominio pasa por Cloudflare) responde `429` con `Retry-After` cuando se pasan: IA 20/min por usuario, sync manual 4/min, importar planillas 10/min, conexión con
Mercado Libre 20/min por IP, `/admin` 60/min por IP y 600/min por IP en general. Es por proceso (con 4 procesos, hasta 4 veces eso). Si un usuario
legítimo choca con un límite, subir el valor en `REGLAS` de `limitador.py`.

## 9. Dependencias

- Dependabot abre una vez por semana un pull request con las actualizaciones; el CI lo prueba.
- El workflow *Vulnerabilidades* corre `pip-audit` cada lunes y cuando cambia `requirements.txt`: si falla, el log nombra el paquete y la versión que lo arregla.
- Después de subir una versión importante (Flask, cryptography, psycopg), probar localmente un sync completo contra la base real antes del deploy.

## 10. Pendientes que dependen del dueño

- **Corregir la hora de las ventas viejas** (una hora atrasadas respecto de Argentina; 35 de 1.092 ventas caen en el día anterior): después del próximo deploy, `python normalizar_horas.py` muestra cuántas cambian (no modifica nada) y `python normalizar_horas.py --aplicar` las corrige. Es seguro repetirlo. Las ventas nuevas ya entran bien.

- `SENTRY_DSN` (para enterarse de errores sin mirar los logs), `MP_ACCESS_TOKEN` (cobro de suscripciones) y `MP_WEBHOOK_SECRET` (la "clave secreta" del panel de webhooks de Mercado Pago: con ella el webhook solo acepta avisos firmados por Mercado Pago).
- Revisión de los términos y la política de privacidad (`legal.py`) por un abogado antes del lanzamiento.
- Un monitor externo de `/healthz/db`.

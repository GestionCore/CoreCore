# CoreLux

Aplicación web para vendedores de Mercado Libre: ganancia real, stock, despacho, costos, publicidad, cobros y más, en un solo lugar.
Es multi-tenant: cada cuenta ve solo sus datos (Row Level Security de Postgres).

> El contexto de decisiones, bugs ya resueltos y reglas de negocio está en [`CLAUDE.md`](CLAUDE.md). Léelo antes de tocar cálculos de plata,
> la sincronización o el aislamiento entre cuentas. La lista de mejoras pendientes está en [`AUDITORIA_2026-10-01.md`](AUDITORIA_2026-10-01.md).

## Stack

- Python (Flask 3) · PostgreSQL en Supabase con `psycopg 3` y pool de conexiones · Row Level Security
- Sincronización con la API de Mercado Libre (catálogo, órdenes, reclamos, preguntas, enriquecimiento) cada 4 minutos y por webhooks
- Producción: Fly.io (`corecore`, región `gru`) con gunicorn + gevent · dominio `corelux.app`

## Arranque local

```bash
python -m venv venv
venv\Scripts\activate            # Windows (en Linux/Mac: source venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env           # completar las variables (ver abajo)
python migrate.py                # aplica las migraciones pendientes
python app.py                    # http://localhost:5000
```

Variables obligatorias (`.env`): `DATABASE_URL` (pooler de **sesión**), `DATABASE_URL_ADMIN`, `MELI_CLIENT_ID`, `MELI_CLIENT_SECRET`,
`MELI_REDIRECT_URI`, `FLASK_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`. Recomendadas: `SENTRY_DSN`, `MP_ACCESS_TOKEN`, `IA_API_KEY`, `ADMIN_EMAIL`.
La app avisa al arrancar cuáles faltan (y en producción no arranca sin las obligatorias). Detalle en `.env.example`.

## Pruebas y calidad

```bash
ruff check .          # nombres indefinidos, imports y variables sin uso
pytest -q             # lógica de plata, seguridad, plantillas y (con DATABASE_URL) aislamiento entre cuentas contra la base real
```

GitHub Actions corre las dos en cada push (`.github/workflows/ci.yml`).

## Estructura

| Dónde | Qué |
|---|---|
| `app.py` | Rutas de la web (en proceso de dividirse en Blueprints: ver `legal.py`, `costos_importar.py`) |
| `seguridad.py` | CSRF por origen, cookies, cabeceras, páginas de error, `/healthz` |
| `db.py`, `auth/` | Conexiones con RLS, OAuth de Mercado Libre, sesión, tokens cifrados |
| `sincronizador.py`, `ventas_sync.py`, `devoluciones_sync.py`, `enriquecimiento.py` | Qué se trae de Mercado Libre y cada cuánto |
| `metricas.py`, `precios.py`, `cobros.py`, `dashboard.py`… | Cálculos y datos de cada pantalla |
| `templates/`, `static/` | Pantallas (componentes `ux-*` en `static/css/ux.css`, macros en `templates/_ux.html`) |
| `migrations/` | Migraciones SQL numeradas e idempotentes (`python migrate.py --status`) |
| `tests/` | Pruebas automáticas |
| `respaldo.py` | Respaldo propio de la base a un zip de CSV |

## Base de datos

- Todo acceso normal pasa por `db.conexion_usuario(usuario_id, cuenta_id)` (RLS activo). `db.conexion_admin()` salta RLS: solo para
  `token_manager.py`, `/admin`, borrado de cuenta, migraciones y respaldos.
- El pooler de Supabase admite **15 conexiones de sesión para todo el proyecto**: `workers × máquinas × DB_POOL_MAX ≤ 12`.
- Respaldo propio: `python respaldo.py` (guarda en `respaldos/`, que no se sube a git).

## Despliegue (Fly.io)

```bash
fly deploy        # aplica las migraciones pendientes (release_command) y reemplaza las máquinas
fly logs -a corecore
```

`FLASK_DEBUG` debe ser `false` en cualquier entorno expuesto. Secretos con `fly secrets set NOMBRE=valor -a corecore`.

## Seguridad y datos personales

- Los pedidos que escriben (POST/PUT/DELETE) solo se aceptan del mismo sitio; los webhooks de Mercado Libre y Mercado Pago están exentos.
- Cada usuario puede eliminar su cuenta y todos sus datos desde `/cuenta/eliminar`. Términos en `/terminos`, privacidad en `/privacidad`.

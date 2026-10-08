"""
Configuración de Gunicorn para CoreLux en producción (Linux/VPS).

Uso:
    gunicorn -c gunicorn.conf.py app:app

Gunicorn NO corre en Windows — en local usá Waitress (vía `python app.py`).
En producción Linux, este archivo reemplaza los flags de línea de comandos.

Dimensionamiento real (Fly.io, 2 máquinas):
  - 2 workers gevent por máquina, hasta 250 conexiones simultáneas cada uno (el trabajo de fondo corre en greenlets: no hay Celery ni Redis)
  - el límite de verdad es el pooler de Supabase: máquinas × workers × DB_POOL_MAX ≤ 12 (ver más abajo y docs/RUNBOOK.md)

Ajustar cuando el monitoreo de Sentry muestre:
  - Latencia > 500ms en p95: revisar primero las consultas y el pool de la base, recién después subir workers
  - Memoria > 80% del RAM: bajar workers
"""
import os

# Binding
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Workers: (2 × CPU) + 1 es la fórmula clásica para I/O-bound.
# Con Celery absorbiendo el trabajo pesado, podemos ser más conservadores.
# En Fly el pooler de Supabase da 15 conexiones de sesión para TODO el proyecto: máquinas × workers × DB_POOL_MAX ≤ 12 (hoy 2 × 2 × 3, ver fly.toml). Nada de
# «2 × CPU + 1»: el Dockerfile ya fija --workers 2 en la línea de comandos (que manda sobre este archivo) y este valor es el respaldo si alguien lo saca.
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
# gevent, como en Fly (el Dockerfile lo pasa también por línea de comandos). El worker de gunicorn parchea la biblioteca estándar al arrancar, ANTES de importar app.py
# (preload_app = False, ver abajo): los `threading.Thread` de `_en_segundo_plano` pasan a ser greenlets. Medido el 2026-10-07 en la máquina de Fly: psycopg 3 (binario) COOPERA con
# gevent: 2 consultas de 2 s en paralelo tardan 2,1 s, no 4. Con «sync» y threads el pooler de Supabase (15 conexiones) se agotaba antes.
worker_class = "gevent"
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "250"))

# Timeouts: 120s para syncs largos (puede tardar varios minutos con muchas ventas)
timeout = 120
keepalive = 5
graceful_timeout = 30

# Logging
accesslog = "-"   # stdout
errorlog = "-"    # stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# Seguridad: recargar workers periódicamente para evitar memory leaks lentos
max_requests = 1000
max_requests_jitter = 100  # evita que todos los workers se recarguen al mismo tiempo

# Preload: en False a propósito. Gunicorn busca este archivo en el
# directorio de trabajo y lo aplica SIEMPRE, incluso cuando el proceso
# real arranca por el Procfile con --worker-class gevent (Railway) — el
# Procfile puede pisar worker_class por CLI, pero no pisa preload_app
# acá. Con preload_app=True, el módulo de la app (y con él requests/
# urllib3/ssl) se importa en el proceso master ANTES de que gevent
# parchee ssl en cada worker — el resultado real, encontrado en
# producción: cualquier pedido HTTPS de la app (ej. auth/oauth_meli.py
# canjeando el code de MeLi) tira "maximum recursion depth exceeded",
# porque queda una mezcla de sockets parcheados y sin parchear. Perder
# el ahorro de RAM de preload es un costo aceptable frente a que el
# login con Mercado Libre no funcione.
preload_app = False

# Para debug de workers colgados
worker_tmp_dir = "/dev/shm"  # /dev/shm es tmpfs (RAM), más rápido que disco

"""
Configuración de Gunicorn para CoreLux en producción (Linux/VPS).

Uso:
    gunicorn -c gunicorn.conf.py app:app

Gunicorn NO corre en Windows — en local usá Waitress (vía `python app.py`).
En producción Linux, este archivo reemplaza los flags de línea de comandos.

Dimensionamiento inicial (VPS de 2 vCPU / 2 GB RAM):
  - 3 workers sync (1 worker idle, 2 atendiendo requests concurrentes)
  - 4 threads por worker = 12 requests concurrentes máximo
  - Con Celery ya manejando el trabajo pesado, Flask no necesita muchos workers

Ajustar cuando el monitoreo de Sentry muestre:
  - Latencia > 500ms en p95: subir workers o threads
  - Memoria > 80% del RAM: bajar workers, subir Celery concurrencia
"""
import multiprocessing
import os

# Binding
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Workers: (2 × CPU) + 1 es la fórmula clásica para I/O-bound.
# Con Celery absorbiendo el trabajo pesado, podemos ser más conservadores.
workers = int(os.getenv("GUNICORN_WORKERS", max(2, multiprocessing.cpu_count())))
worker_class = "sync"
threads = int(os.getenv("GUNICORN_THREADS", "4"))

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

# Preload: carga el módulo de la app antes de forkear los workers.
# Ahorra RAM (código compartido) y detecta errores de import al arrancar.
preload_app = True

# Para debug de workers colgados
worker_tmp_dir = "/dev/shm"  # /dev/shm es tmpfs (RAM), más rápido que disco

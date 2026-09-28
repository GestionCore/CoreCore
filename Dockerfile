# Imagen para Fly.io — Railway usaba Nixpacks (detección automática), acá
# hace falta el Dockerfile a mano porque Fly.io lo pide explícito.
# python:3.13-slim porque es la versión que Railway venía corriendo en
# producción (confirmado por el traceback real: /app/.venv/lib/python3.13/...)
# — no 3.14 como el entorno local de desarrollo en Windows, para no meter
# una variable más justo en la migración de hosting.
FROM python:3.13-slim

WORKDIR /app

# psycopg[binary] ya trae su propio libpq compilado (no hace falta
# libpq-dev), pero sí hacen falta unas librerías de sistema mínimas para
# que "cryptography" y "Pillow" levanten en Debian slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# gunicorn.conf.py trae ajustes de producción reales (preload_app=False
# a propósito — es el fix del RecursionError que rompía el login con
# MeLi bajo gevent, ver el comentario del propio archivo; max_requests
# para reciclar workers; worker_tmp_dir en /dev/shm) — se usa como base
# con -c, y los flags de CLI encima son los mismos que ya probamos en
# Railway (2 workers gevent, el ajuste para que el sync en background no
# bloquee los pedidos web compartiendo un solo worker).
CMD ["gunicorn", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:8080", "--workers", "2", "--worker-class", "gevent", "--worker-connections", "250", "--timeout", "60", "--graceful-timeout", "30", "app:app"]

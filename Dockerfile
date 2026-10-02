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
# que "cryptography" y "Pillow" levanten en Debian slim. tzdata hace
# falta para poder fijar la zona horaria de abajo — python:3.13-slim no
# la trae instalada de fábrica.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# CRÍTICO: toda la app (Despacho, Stock, Dashboard, resúmenes "de hoy",
# etc.) usa datetime.now() sin timezone asumiendo que el reloj del
# sistema ya está en hora de Argentina — cierto en la PC de Diego
# (Windows, donde nació la app) pero NO en un contenedor Docker, que por
# defecto corre en UTC. Sin esto, entre las 21:00 y las 00:00 hora
# Argentina el contenedor ya "cree" que es el día siguiente (UTC), así
# que cualquier resumen "de hoy" filtraba por una fecha que todavía no
# tenía ventas — parecía que no había pasado nada en el día.
ENV TZ=America/Argentina/Buenos_Aires

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Versión (commit) que corre: la pasa desplegar.py con --build-arg y /healthz la informa, así se puede confirmar qué código quedó en producción.
ARG GIT_SHA=desconocida
ENV CORELUX_VERSION=${GIT_SHA}

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

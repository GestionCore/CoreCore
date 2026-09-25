"""
Configuración de Gunicorn para producción (Linux). En Windows se sigue
usando Waitress (ver `if __name__ == "__main__"` en app.py) — Gunicorn
no corre en Windows, por eso esto vive separado y no lo toca el dev local.

Arrancar (lo hace el servicio systemd, no hace falta a mano):
    venv/bin/gunicorn -c deploy/gunicorn_config.py app:app
"""
import multiprocessing

# nginx hace de proxy inverso adelante (con el certificado SSL) y le
# pasa el tráfico a esto por localhost — Gunicorn nunca queda expuesto
# directo a internet.
bind = "127.0.0.1:5000"

workers = multiprocessing.cpu_count() * 2 + 1

# La app hace muchas llamadas salientes a la API de MeLi (sync, Ads,
# Facturación) — son esperas de red, no cómputo. "gevent" deja que cada
# worker atienda varias requests mientras alguna está esperando esa
# respuesta, en vez de bloquearse una por una como el modo "sync" por
# default. Con el volumen de esta app (dashboard, no una API masiva),
# esto alcanza de sobra sin sumar más workers/RAM.
worker_class = "gevent"
worker_connections = 250

# Alto a propósito: la sincronización inicial de una cuenta nueva y
# algunas consultas a Ads pueden tardar bastante — un timeout corto
# mataría el worker a mitad de una sync real.
timeout = 60
graceful_timeout = 30
keepalive = 5

# Recicla cada worker después de N requests — red de seguridad barata
# contra una fuga de memoria lenta que todavía no se detectó.
max_requests = 1000
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
loglevel = "info"

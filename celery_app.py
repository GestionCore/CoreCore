"""
Instancia de Celery para CoreLux.

Responsabilidades:
  - Cola de tareas: webhooks de MeLi y syncs iniciales, que antes usaban
    threading.Thread(daemon=True). Con Celery, si el servidor se reinicia
    con una tarea en vuelo, la tarea se reencola automáticamente y se
    reintenta cuando el worker vuelve (task_acks_late=True).
  - Beat scheduler: reemplaza APScheduler para las tareas periódicas.
    Correr en proceso separado: `celery -A celery_app beat -l info`
  - Workers: 1 worker en dev (--pool=solo en Windows), múltiples en Linux.

Cómo arrancar en desarrollo (Windows):
    celery -A celery_app worker --pool=solo --loglevel=info
    celery -A celery_app beat --loglevel=info

Cómo arrancar en producción (Linux):
    celery -A celery_app worker --concurrency=4 --loglevel=info
    celery -A celery_app beat --loglevel=info

No importa app.py para evitar el ciclo de dependencias. Las tasks
importan directamente los módulos de negocio (sincronizador, db, etc.)
que no tienen dependencia de Flask.
"""
from celery import Celery
from celery.schedules import crontab
import config

celery = Celery(
    "corelux",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
    include=[
        "tasks.sync_tasks",
        "tasks.webhook_tasks",
        "tasks.health_tasks",
    ],
)

celery.conf.update(
    # Serialización
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone (Argentina)
    timezone="America/Argentina/Buenos_Aires",
    enable_utc=True,

    # Confiabilidad: ACK DESPUÉS de que la tarea termina.
    # Si el worker cae a mitad de una tarea, la tarea vuelve a la cola.
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Límites de tiempo: 5 min soft (recibe SIGTERM, puede limpiar),
    # 10 min hard (SIGKILL — sin importar qué).
    task_soft_time_limit=300,
    task_time_limit=600,

    # Reintentos: límite explícito para no ciclar para siempre.
    task_max_retries=3,

    # Resultados: expirar en 1 hora (no los usamos, pero evita que Redis
    # crezca indefinidamente con resultados acumulados).
    result_expires=3600,

    # Beat schedule — reemplaza APScheduler
    beat_schedule={
        "sincronizar-catalogos-y-ventas": {
            "task": "tasks.sync_tasks.tarea_sincronizar_todo",
            "schedule": 240.0,  # cada 4 minutos
        },
        "relevar-competencia": {
            "task": "tasks.sync_tasks.tarea_relevar_competencia",
            "schedule": 86400.0,  # cada 24 horas
        },
        "analizar-combos": {
            "task": "tasks.sync_tasks.tarea_analizar_combos",
            "schedule": 604800.0,  # cada 7 días
        },
        "verificar-salud-tokens": {
            "task": "tasks.health_tasks.tarea_verificar_tokens",
            "schedule": 3600.0,  # cada hora
        },
    },
)

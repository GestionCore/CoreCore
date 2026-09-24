"""
Tarea de procesamiento de webhooks de MeLi.

Antes: threading.Thread(daemon=True) en app.py — si Flask se reiniciaba
con una notificación en vuelo, esa notificación se perdía y MeLi la
reintentaba eventualmente, pero sin garantía.

Ahora: el webhook HTTP responde 200 inmediatamente y encola esta tarea.
Celery la procesa con reintentos automáticos. Si el worker cae, la tarea
vuelve a la cola. Si MeLi reintenta la notificación, el ON CONFLICT DO
UPDATE de sincronizador.py maneja el duplicado sin problema.

Reintentos: 3 intentos con backoff exponencial (30s, 60s, 120s).
Si los 3 fallan, el error va a Sentry y la notificación se descarta
(MeLi va a reintentar por su cuenta de todos modos).
"""
from celery_app import celery
import sincronizador


@celery.task(
    bind=True,
    name="tasks.webhook_tasks.procesar_webhook_task",
    max_retries=3,
    default_retry_delay=30,
    # No queremos que un webhook mal formado llene la cola con reintentos.
    # Errores de datos (missing topic/resource) se ignoran silenciosamente.
    ignore_result=True,
)
def procesar_webhook_task(self, topic, resource, meli_user_id):
    """
    Procesa una notificación webhook de MeLi en background.
    Encolada desde /webhook en app.py (responde 200 antes de procesar).
    """
    try:
        sincronizador.procesar_notificacion_webhook(topic, resource, meli_user_id)
    except Exception as exc:
        print(f"[Celery] ❌ procesar_webhook_task: topic={topic}, user={meli_user_id}: {exc}")
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

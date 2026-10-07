"""
Objetivo de respuesta de las preguntas de compradores.

Mercado Libre mide el tiempo de respuesta del vendedor (GET /users/{id}/questions/response_time, separado en horario laboral, fuera de horario y fines de
semana), pero NO informa un plazo por pregunta: la respuesta real de /questions/search solo trae `date_created`. Por eso el límite que se muestra es un
objetivo interno de CoreLux: responder dentro de SLA_MINUTOS desde que la pregunta entró. Sirve para ordenar la cola por urgencia real, no es una fecha de Mercado Libre.
"""
import re
from datetime import datetime, timedelta, timezone

SLA_MINUTOS = 60                # el mismo «rápido» que usa tiempo_respuesta.py
AVISO_MINUTOS = 15              # a partir de acá, «por vencer»


def fecha_de_meli(texto):
    """datetime con zona de «2026-04-18T09:03:35.262291905-04:00» (Mercado Libre manda hasta 9 decimales: Python solo entiende 6), o None. El instante es el correcto."""
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(texto)))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def limite_de(fecha_pregunta, sla_minutos=SLA_MINUTOS):
    return fecha_pregunta + timedelta(minutes=sla_minutos) if fecha_pregunta else None


def urgencia(limite, ahora=None):
    """('vencida' | 'por_vencer' | 'a_tiempo' | 'sin_dato', minutos que faltan; negativos = ya pasó)."""
    if not limite:
        return "sin_dato", None
    ahora = ahora or datetime.now(timezone.utc)
    faltan = int((limite - ahora).total_seconds() // 60)
    if faltan < 0:
        return "vencida", faltan
    return ("por_vencer" if faltan <= AVISO_MINUTOS else "a_tiempo"), faltan

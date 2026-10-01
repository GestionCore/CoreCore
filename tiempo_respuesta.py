"""
Cuánto tarda el vendedor en responder las preguntas de los compradores (mediana de las últimas respondidas).

Responder rápido pesa en la conversión y en la reputación. GET /questions/search?status=ANSWERED trae, por pregunta, cuándo se hizo y cuándo se
respondió; no hace falta guardar nada en la base: se consulta (con caché por cuenta en quien llama) y se resume.
"""
from datetime import datetime
import meli_http

MUESTRA = 50
UMBRAL_BUENO_MIN = 60        # hasta 1 hora: rápido
UMBRAL_JUSTO_MIN = 24 * 60   # hasta 1 día: a tiempo


def _minutos(pregunta):
    a = (pregunta.get("answer") or {}).get("date_created")
    q = pregunta.get("date_created")
    if not a or not q:
        return None
    try:
        return max((datetime.fromisoformat(a) - datetime.fromisoformat(q)).total_seconds() / 60, 0)
    except ValueError:
        return None


def calcular(access_token, seller_id):
    """{"mediana_min", "promedio_min", "pct_en_1h", "muestra", "tono"} o None si no hay preguntas respondidas / MeLi no respondió."""
    try:
        resp = meli_http.get("https://api.mercadolibre.com/questions/search", headers={"Authorization": f"Bearer {access_token}"},
                             params={"seller_id": seller_id, "status": "ANSWERED", "limit": MUESTRA, "sort_fields": "date_created", "sort_types": "DESC"},
                             timeout=10)
    except Exception as e:
        print(f"[TiempoRespuesta] ⚠️ No se pudo consultar las preguntas respondidas: {e}")
        return None
    if resp.status_code != 200:
        return None
    minutos = sorted(m for m in (_minutos(q) for q in resp.json().get("questions") or []) if m is not None)
    if not minutos:
        return None
    mediana = minutos[len(minutos) // 2]
    return {
        "mediana_min": round(mediana), "promedio_min": round(sum(minutos) / len(minutos)), "muestra": len(minutos),
        "pct_en_1h": round(sum(1 for m in minutos if m <= UMBRAL_BUENO_MIN) / len(minutos) * 100),
        "tono": "ok" if mediana <= UMBRAL_BUENO_MIN else ("warn" if mediana <= UMBRAL_JUSTO_MIN else "danger"),
    }

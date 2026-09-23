"""
Reputación y Confianza: datos reales y oficiales de tu cuenta en MeLi
(nivel, Mercado Líder, historial de transacciones, calificaciones y las
métricas de calidad que arman ese nivel) — todo desde /users/$USER_ID,
el mismo recurso oficial que usa MeLi para calcular tu reputación.
"""
import requests

NOMBRES_NIVEL = {
    "5_green": "Excelente (verde)",
    "4_light_green": "Muy bueno (verde claro)",
    "3_yellow": "Bueno (amarillo)",
    "2_orange": "Regular (naranja)",
    "1_red": "A mejorar (rojo)",
}

NOMBRES_POWER_SELLER = {
    "platinum": "Platinum",
    "gold": "Gold",
    "silver": "Silver",
}


def obtener_reputacion(access_token, user_id):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(f"https://api.mercadolibre.com/users/{user_id}", headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[Reputación] ⚠️ Error consultando reputación: {resp.status_code} - {resp.text[:200]}")
            return None

        data = resp.json()
        rep = data.get("seller_reputation", {}) or {}
        transacciones = rep.get("transactions", {}) or {}
        ratings = transacciones.get("ratings", {}) or {}
        metricas = rep.get("metrics", {}) or {}

        nivel_id = rep.get("level_id")
        power_status = rep.get("power_seller_status")

        total = transacciones.get("total", 0) or 0
        completadas = transacciones.get("completed", 0) or 0
        canceladas = transacciones.get("canceled", 0) or 0
        tasa_cancelacion = round((canceladas / total) * 100, 1) if total > 0 else 0.0

        def _extraer_metrica(clave):
            m = metricas.get(clave, {}) or {}
            return {
                "tasa": m.get("rate"),
                "valor": m.get("value"),
            }

        return {
            "nivel_id": nivel_id,
            "nivel_nombre": NOMBRES_NIVEL.get(nivel_id, nivel_id or "Sin nivel todavía"),
            "power_seller_status": power_status,
            "power_seller_nombre": NOMBRES_POWER_SELLER.get(power_status, power_status),
            "total_transacciones": total,
            "completadas": completadas,
            "canceladas": canceladas,
            "tasa_cancelacion": tasa_cancelacion,
            "ratings_positivas": ratings.get("positive", 0) or 0,
            "ratings_neutras": ratings.get("neutral", 0) or 0,
            "ratings_negativas": ratings.get("negative", 0) or 0,
            "reclamos": _extraer_metrica("claims"),
            "demora_en_despacho": _extraer_metrica("delayed_handling_time"),
            "cancelaciones_metrica": _extraer_metrica("cancellations"),
        }
    except Exception as e:
        print(f"[Reputación] ❌ Error de conexión: {e}")
        return None

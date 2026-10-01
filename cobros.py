"""
Cobros: cuánta plata te va a acreditar Mercado Libre, cuándo, y cuánta está retenida por reclamos.

Todo sale de lo que ya guarda el sync, sin llamar a la API:
  · ventas.monto_liberacion / fecha_liberacion: lo que Mercado Pago deposita de verdad (ya sin comisiones ni envío) y cuándo se acredita;
  · incidencias_posventa.monto_retenido: el pago de la orden en "in_mediation" mientras el reclamo sigue abierto.
Sirve a cualquier vendedor y rubro: es el calendario de cobro de su cuenta.
"""
from datetime import date, timedelta

DIAS_VISTA = 30          # los próximos depósitos se agrupan hasta 30 días; lo posterior va en "más adelante"
DIAS_ACREDITADO = 30


def obtener_datos(cursor, cuenta_id, hoy=None):
    hoy = hoy or date.today()
    cursor.execute("""
        SELECT fecha_liberacion, COUNT(*), COALESCE(SUM(monto_liberacion), 0)
        FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_liberacion >= %s AND monto_liberacion IS NOT NULL
        GROUP BY fecha_liberacion ORDER BY fecha_liberacion
    """, (cuenta_id, hoy))
    dias = [{"fecha": f, "ventas": int(n), "monto": float(m)} for f, n, m in cursor.fetchall()]

    limite = hoy + timedelta(days=DIAS_VISTA)
    total = sum(d["monto"] for d in dias)
    manana = hoy + timedelta(days=1)
    def _suma(desde, hasta):
        return round(sum(d["monto"] for d in dias if desde <= d["fecha"] <= hasta), 2)

    for d in dias:
        delta = (d["fecha"] - hoy).days
        d["cuando"] = "hoy" if delta == 0 else ("mañana" if delta == 1 else f"en {delta} días")
    maximo = max((d["monto"] for d in dias), default=0)
    for d in dias:
        d["pct"] = max(round(d["monto"] / maximo * 100), 3) if maximo else 0

    cursor.execute("""
        SELECT COALESCE(SUM(monto_liberacion), 0), COUNT(*) FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND fecha_liberacion >= %s AND fecha_liberacion < %s AND monto_liberacion IS NOT NULL
    """, (cuenta_id, hoy - timedelta(days=DIAS_ACREDITADO), hoy))
    acreditado, ventas_acreditadas = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_liberacion IS NULL AND monto_liberacion IS NULL
          AND fecha_venta >= %s
    """, (cuenta_id, hoy - timedelta(days=60)))
    sin_fecha = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT id_orden, tipo, motivo, estado, monto_retenido, fecha, afecta_reputacion FROM incidencias_posventa
        WHERE cuenta_id = %s AND estado NOT IN ('closed', 'resolved') AND COALESCE(monto_retenido, 0) > 0 ORDER BY monto_retenido DESC
    """, (cuenta_id,))
    retenidos = [{"id_orden": o, "tipo": t, "motivo": m, "estado": e, "monto": float(r), "fecha": f.strftime("%d/%m") if f else None,
                  "sin_impacto": a == "not_affected", "link": f"https://www.mercadolibre.com.ar/ventas/{o}/detalle"} for o, t, m, e, r, f, a in cursor.fetchall()]

    return {
        "dias": [d for d in dias if d["fecha"] <= limite], "total": round(total, 2), "total_dias": len(dias),
        "hoy": _suma(hoy, hoy), "manana": _suma(manana, manana), "semana": _suma(hoy, hoy + timedelta(days=7)),
        "mes": _suma(hoy, limite), "mas_adelante": round(sum(d["monto"] for d in dias if d["fecha"] > limite), 2),
        "proximo": dias[0] if dias else None, "acreditado": round(float(acreditado), 2), "dias_acreditado": DIAS_ACREDITADO,
        "ventas_acreditadas": int(ventas_acreditadas or 0), "sin_fecha": int(sin_fecha),
        "retenidos": retenidos, "retenido_total": round(sum(r["monto"] for r in retenidos), 2), "dias_vista": DIAS_VISTA,
    }

"""
Precio mínimo y precio recomendado por publicación.

Con la comisión y el envío REALES que pagó cada publicación en sus ventas de los últimos 90 días (ventas.cargo_venta ya incluye
comisión, financiación y cupones; ventas.costo_envio es lo que cobró el correo o la logística) y el costo de fabricación cargado,
calcula:
  · precio mínimo: el que deja la ganancia neta en $0 (por debajo, cada venta pierde plata);
  · precio recomendado: el que deja el margen objetivo que elige el usuario.

neto por unidad = P × (1 − comisión% − publicidad%) − envío por unidad − costo de fabricación
Solo se calcula con datos reales de la propia publicación (el envío de una remera y el de una campera no se parecen, y menos entre
rubros): con 1 o 2 ventas se marca como "pocas ventas" y las que todavía no vendieron quedan aparte, sin estimar.
Sirve a cualquier rubro: no depende de talles, categorías ni de un tipo de logística.
"""
import math

VENTANA_DIAS = 90
MIN_UNIDADES_PROPIAS = 3          # con menos ventas el cálculo se muestra como orientativo ("pocas ventas")
MARGEN_OBJETIVO_DEFECTO = 20.0
REDONDEO = 10                     # los precios se redondean hacia arriba al múltiplo de $10


def _subir(precio):
    return math.ceil(precio / REDONDEO) * REDONDEO


def _entre(valor, minimo, maximo, defecto):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return defecto
    return min(max(v, minimo), maximo)


def parametros(margen, publicidad):
    """Margen objetivo (0–60 %) y peso de la publicidad en el precio (0–40 %), saneados."""
    return _entre(margen, 0, 60, MARGEN_OBJETIVO_DEFECTO), _entre(publicidad, 0, 40, 0.0)


def obtener_datos(cursor, cuenta_id, margen_objetivo=MARGEN_OBJETIVO_DEFECTO, publicidad_pct=0.0):
    cursor.execute("""
        SELECT id_meli, SUM(cantidad), SUM(precio_venta * cantidad), SUM(COALESCE(cargo_venta, 0)), SUM(COALESCE(costo_envio, 0))
        FROM ventas
        WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta >= current_date - %s
        GROUP BY id_meli
    """, (cuenta_id, VENTANA_DIAS))
    ventas = {r[0]: {"u": int(r[1] or 0), "ingreso": float(r[2] or 0), "cargos": float(r[3] or 0), "envios": float(r[4] or 0)} for r in cursor.fetchall()}

    cursor.execute("""
        SELECT id_meli, titulo, thumbnail, permalink, precio, precio_costo
        FROM productos_padre
        WHERE cuenta_id = %s AND estado = 'active' AND precio > 0
        ORDER BY titulo
    """, (cuenta_id,))
    filas = cursor.fetchall()

    pub = publicidad_pct / 100
    obj = margen_objetivo / 100
    items, sin_costo, sin_ventas = [], [], []
    for id_meli, titulo, thumbnail, permalink, precio, costo in filas:
        precio = float(precio)
        costo = float(costo or 0)
        v = ventas.get(id_meli) or {"u": 0, "ingreso": 0.0, "cargos": 0.0, "envios": 0.0}
        base = {"id_meli": id_meli, "titulo": titulo or id_meli, "thumbnail": thumbnail, "permalink": permalink, "precio": precio,
                "costo": costo, "unidades": v["u"], "estimado": v["u"] < MIN_UNIDADES_PROPIAS}
        if costo <= 0:
            sin_costo.append(base)
            continue
        if v["u"] < 1 or v["ingreso"] <= 0:
            sin_ventas.append(base)
            continue
        comision = v["cargos"] / v["ingreso"]
        envio = v["envios"] / v["u"]

        fijo = costo + envio
        margen_pct_precio = 1 - comision - pub     # la parte del precio que queda después de comisión y publicidad
        neto_unitario = precio * margen_pct_precio - fijo
        minimo = _subir(fijo / margen_pct_precio) if margen_pct_precio > 0 else None
        denom = margen_pct_precio - obj
        recomendado = _subir(fijo / denom) if denom > 0 else None
        margen_actual = neto_unitario / precio * 100

        if minimo is not None and precio < minimo:
            estado = "pierde"
        elif recomendado is not None and precio < recomendado:
            estado = "justo"
        else:
            estado = "ok"
        items.append({**base, "comision_pct": round(comision * 100, 1), "envio": round(envio, 2), "neto_unitario": round(neto_unitario, 2),
                      "margen_actual": round(margen_actual, 1), "minimo": minimo, "recomendado": recomendado, "estado": estado,
                      "perdida_mensual": round(-neto_unitario * v["u"] / (VENTANA_DIAS / 30), 2) if (neto_unitario < 0 and v["u"]) else 0.0})

    # La regla de precios: de 0 a un poco más que lo más alto entre el recomendado y el actual
    for i in items:
        tope = max(i["recomendado"] or 0, i["minimo"] or 0, i["precio"]) * 1.12
        i["tope"] = tope
        i["pos_minimo"] = round((i["minimo"] or 0) / tope * 100, 1) if i["minimo"] else None
        i["pos_recomendado"] = round((i["recomendado"] or 0) / tope * 100, 1) if i["recomendado"] else None
        i["pos_actual"] = round(i["precio"] / tope * 100, 1)
        i["diferencia"] = (i["recomendado"] - i["precio"]) if i["recomendado"] else None

    orden = {"pierde": 0, "justo": 1, "ok": 2}
    items.sort(key=lambda i: (orden[i["estado"]], -i["perdida_mensual"], -i["unidades"], i["titulo"]))
    pierden = [i for i in items if i["estado"] == "pierde"]
    justos = [i for i in items if i["estado"] == "justo"]
    return {
        "items": items, "pierden": pierden, "justos": justos, "bien": [i for i in items if i["estado"] == "ok"], "sin_costo": sin_costo, "sin_ventas": sin_ventas,
        "total_activas": len(items) + len(sin_costo) + len(sin_ventas), "perdida_mensual": round(sum(i["perdida_mensual"] for i in pierden), 2),
        "margen_objetivo": margen_objetivo, "publicidad_pct": publicidad_pct, "ventana_dias": VENTANA_DIAS,
        "pocas_ventas": sum(1 for i in items if i["estimado"]),
    }

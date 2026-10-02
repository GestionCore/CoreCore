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

import meli_http

VENTANA_DIAS = 90
MIN_UNIDADES_PROPIAS = 3          # con menos ventas el cálculo se muestra como orientativo ("pocas ventas")
MARGEN_OBJETIVO_DEFECTO = 20.0
REDONDEO = 10                     # los precios se redondean hacia arriba al múltiplo de $10
MAX_SUBA_PCT = 60                 # una suba mayor casi siempre es un costo de fabricación mal cargado: no se aplica sin revisarlo
MAXIMO_POR_PEDIDO = 50
URL_ITEM = "https://api.mercadolibre.com/items/{}"


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
        i["suba_pct"] = round((i["recomendado"] / i["precio"] - 1) * 100, 1) if i["recomendado"] and i["recomendado"] > i["precio"] else None
        i["suba_excesiva"] = bool(i["suba_pct"] and i["suba_pct"] > MAX_SUBA_PCT)
        i["aplicable"] = bool(i["suba_pct"]) and not i["suba_excesiva"]

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


def aplicables(datos):
    """Publicaciones a las que se puede aplicar el precio recomendado: pierden o tienen margen justo, el recomendado es más alto y la suba es razonable."""
    return {i["id_meli"]: i for i in datos["pierden"] + datos["justos"] if i["aplicable"]}


def _mensaje_de_error(respuesta):
    try:
        cuerpo = respuesta.json()
        return str(cuerpo.get("message") or cuerpo.get("error") or respuesta.status_code)[:160]
    except Exception:
        return f"Mercado Libre respondió {respuesta.status_code}"


def aplicar(cursor, cuenta_id, access_token, cambios, datos):
    """
    Sube el precio de las publicaciones pedidas al recomendado. `cambios` es [{"id", "precio"}] y se valida contra `datos` (recalculado en el
    servidor): solo se acepta el precio recomendado exacto de una publicación aplicable, nunca un valor arbitrario ni uno que quedó viejo
    porque cambió el costo o el margen. Devuelve [{"id", "ok", "detalle", "precio"}]; una que falla no corta a las demás.
    """
    permitidas = aplicables(datos)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resultados, vistos = [], set()
    for c in (cambios or [])[:MAXIMO_POR_PEDIDO]:
        id_meli = str((c or {}).get("id") or "")
        if not id_meli or id_meli in vistos:
            continue
        vistos.add(id_meli)
        item = permitidas.get(id_meli)
        try:
            pedido = float((c or {}).get("precio"))
        except (TypeError, ValueError):
            pedido = None
        if item is None:
            resultados.append({"id": id_meli, "ok": False, "detalle": "Ya no es aplicable: el precio, el costo o el margen cambiaron. Recargá la página."})
            continue
        if pedido is None or abs(pedido - item["recomendado"]) > 0.005:
            resultados.append({"id": id_meli, "ok": False, "detalle": "El precio recomendado cambió desde que lo viste. Recargá la página."})
            continue
        try:
            r = meli_http.put(URL_ITEM.format(id_meli), headers=headers, json={"price": item["recomendado"]})
        except Exception as e:
            resultados.append({"id": id_meli, "ok": False, "detalle": f"No se pudo conectar con Mercado Libre: {e}"[:160]})
            continue
        if r.status_code not in (200, 201):
            resultados.append({"id": id_meli, "ok": False, "detalle": _mensaje_de_error(r)})
            continue
        cursor.execute("UPDATE productos_padre SET precio = %s WHERE cuenta_id = %s AND id_meli = %s", (item["recomendado"], cuenta_id, id_meli))
        cursor.execute(
            "INSERT INTO historial_precios (cuenta_id, id_meli, precio_anterior, precio_nuevo, fecha_cambio) VALUES (%s, %s, %s, %s, now())",
            (cuenta_id, id_meli, item["precio"], item["recomendado"]),
        )
        resultados.append({"id": id_meli, "ok": True, "detalle": "Precio actualizado", "precio": item["recomendado"]})
    return resultados

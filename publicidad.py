"""Publicidad (página propia) — portado de Santi Mens."""
import db
import ads
from utils import formatear_moneda


def calcular_datos_publicidad(usuario_id, cuenta_id, access_token, fecha_desde, fecha_hasta):
    advertiser_id = ads.obtener_advertiser_id(access_token, cuenta_id)
    if not advertiser_id:
        return None

    campanas = ads.obtener_campanas_con_metricas(access_token, advertiser_id, fecha_desde, fecha_hasta)
    serie_diaria = ads.obtener_serie_diaria_ads(access_token, advertiser_id, fecha_desde, fecha_hasta)

    costo_total = sum(c["costo"] for c in campanas)
    ventas_atribuidas_total = sum(c["ventas_atribuidas"] for c in campanas)
    clicks_total = sum(c["clicks"] for c in campanas)
    unidades_total = sum(c["unidades"] for c in campanas)

    roas_general = round(ventas_atribuidas_total / costo_total, 2) if costo_total > 0 else None
    acos_general = round((costo_total / ventas_atribuidas_total) * 100, 1) if ventas_atribuidas_total > 0 else None

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde, fecha_hasta))
        facturacion_total_negocio = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT DISTINCT id_meli, titulo FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde, fecha_hasta))
        items_con_ventas = cursor.fetchall()

    tacos = round((costo_total / facturacion_total_negocio) * 100, 1) if facturacion_total_negocio > 0 else None

    costo_ads_por_publicacion = []
    if items_con_ventas:
        ids_relevantes = [r[0] for r in items_con_ventas]
        titulos_por_id = dict(items_con_ventas)
        costos_por_item = ads.obtener_costos_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_relevantes)
        items_ordenados = sorted(costos_por_item.items(), key=lambda x: -x[1])
        for id_meli, costo in items_ordenados:
            costo_ads_por_publicacion.append({"id_meli": id_meli, "titulo": titulos_por_id.get(id_meli, id_meli), "costo_formateado": formatear_moneda(costo)})

    for c in campanas:
        c["costo_formateado"] = formatear_moneda(c["costo"])
        c["ventas_atribuidas_formateado"] = formatear_moneda(c["ventas_atribuidas"])
        c["presupuesto_formateado"] = formatear_moneda(c["presupuesto"]) if c["presupuesto"] else None
        c["roas_bajo"] = c["roas"] is not None and c["roas"] < 3

        c["pct_presupuesto"] = round((c["costo"] / c["presupuesto"]) * 100, 1) if c["presupuesto"] else None
        c["recomendacion"] = None
        if c["estado"] == "active" and c["roas"] is not None:
            presupuesto_alto_uso = c["pct_presupuesto"] is not None and c["pct_presupuesto"] >= 80
            if c["roas_bajo"] and presupuesto_alto_uso:
                c["recomendacion"] = {"tipo": "urgente", "texto": "ROAS bajo y presupuesto casi agotado — pausala o bajale el presupuesto antes de seguir gastando sin retorno."}
            elif c["roas"] >= 5 and presupuesto_alto_uso:
                c["recomendacion"] = {"tipo": "oportunidad", "texto": "Está funcionando muy bien y se está por quedar sin presupuesto — subilo si querés capturar más ventas."}
            elif c["roas_bajo"] and not presupuesto_alto_uso:
                c["recomendacion"] = {"tipo": "esperar", "texto": "ROAS bajo pero recién arrancando el presupuesto — dale unos días más antes de decidir."}

    campanas.sort(key=lambda c: -c["costo"])

    dias_ordenados = sorted(serie_diaria.keys())
    chart_data = {
        "labels": [d[8:10] + "/" + d[5:7] for d in dias_ordenados],
        "gasto": [round(serie_diaria[d]["costo"], 2) for d in dias_ordenados],
        "ventas": [round(serie_diaria[d]["ventas"], 2) for d in dias_ordenados],
        "unidades": [serie_diaria[d]["unidades"] for d in dias_ordenados],
    }

    return {
        "campanas": campanas, "costo_total_formateado": formatear_moneda(costo_total),
        "ventas_atribuidas_formateado": formatear_moneda(ventas_atribuidas_total),
        "clicks_total": clicks_total, "unidades_total": unidades_total,
        "roas_general": roas_general, "acos_general": acos_general, "tacos": tacos,
        "facturacion_total_negocio_formateada": formatear_moneda(facturacion_total_negocio),
        "chart_data": chart_data, "costo_ads_por_publicacion": costo_ads_por_publicacion[:10],
    }

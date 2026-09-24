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
    venta_directa_total = sum(c["venta_directa"] for c in campanas)
    venta_indirecta_total = sum(c["venta_indirecta"] for c in campanas)

    roas_general = round(ventas_atribuidas_total / costo_total, 2) if costo_total > 0 else None
    acos_general = round((costo_total / ventas_atribuidas_total) * 100, 1) if ventas_atribuidas_total > 0 else None

    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT
                COALESCE(SUM(v.precio_venta*v.cantidad),0) AS facturado,
                COALESCE(SUM(v.cargo_venta),0) AS comision,
                COALESCE(SUM(v.costo_envio),0) AS envios,
                COALESCE(SUM(COALESCE(p.precio_costo,0)*v.cantidad),0) AS costo_fabricacion
            FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.fecha_venta BETWEEN %s AND %s
        """, (fecha_desde, fecha_hasta))
        facturacion_total_negocio, comision_total, envios_total, costo_fabricacion_total = (float(x or 0.0) for x in cursor.fetchone())

        cursor.execute("SELECT DISTINCT id_meli, titulo FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde, fecha_hasta))
        items_con_ventas = cursor.fetchall()

    tacos = round((costo_total / facturacion_total_negocio) * 100, 1) if facturacion_total_negocio > 0 else None

    # D5: directa (vendiste lo anunciado) vs. indirecta (compraron otra
    # cosa del catálogo por haber llegado al anuncio).
    venta_atribuida_direccional = venta_directa_total + venta_indirecta_total
    pct_venta_directa = round(venta_directa_total / venta_atribuida_direccional * 100, 1) if venta_atribuida_direccional > 0 else None
    pct_venta_indirecta = round(100 - pct_venta_directa, 1) if pct_venta_directa is not None else None

    # D6: cuánto del total facturado por el negocio vino de un click
    # pago vs. orgánico (búsqueda/catálogo sin publicidad de por medio).
    pct_origen_pagado = round(min(ventas_atribuidas_total, facturacion_total_negocio) / facturacion_total_negocio * 100, 1) if facturacion_total_negocio > 0 else None
    pct_origen_organico = round(100 - pct_origen_pagado, 1) if pct_origen_pagado is not None else None

    # D2/D3: ROAS de equilibrio — el mínimo para que la pauta no te
    # coma margen. Con margen de contribución M% (sin contar el gasto
    # de ads), necesitás vender ROAS >= 1/M para no perder plata en
    # cada click pago. margen_sin_ads a propósito NO resta el costo de
    # ads (es la variable que estamos evaluando).
    roas_equilibrio = None
    margen_sin_ads_pct = None
    if facturacion_total_negocio > 0:
        margen_sin_ads = facturacion_total_negocio - comision_total - envios_total - costo_fabricacion_total
        margen_sin_ads_pct = round((margen_sin_ads / facturacion_total_negocio) * 100, 1)
        if margen_sin_ads > 0:
            roas_equilibrio = round(facturacion_total_negocio / margen_sin_ads, 2)
    te_deja_ganancia = (roas_general >= roas_equilibrio) if (roas_general is not None and roas_equilibrio is not None) else None

    roas_slider = None
    if roas_general is not None and roas_equilibrio is not None:
        techo = max(roas_general, roas_equilibrio, 1) * 1.3
        roas_slider = {
            "pct_actual": round(min(roas_general / techo * 100, 100), 1),
            "pct_equilibrio": round(min(roas_equilibrio / techo * 100, 100), 1),
        }

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
        "roas_equilibrio": roas_equilibrio, "margen_sin_ads_pct": margen_sin_ads_pct, "te_deja_ganancia": te_deja_ganancia,
        "roas_slider": roas_slider,
        "pct_venta_directa": pct_venta_directa, "pct_venta_indirecta": pct_venta_indirecta,
        "venta_directa_formateada": formatear_moneda(venta_directa_total), "venta_indirecta_formateada": formatear_moneda(venta_indirecta_total),
        "pct_origen_pagado": pct_origen_pagado, "pct_origen_organico": pct_origen_organico,
        "ventas_organicas_formateada": formatear_moneda(max(facturacion_total_negocio - ventas_atribuidas_total, 0)),
    }

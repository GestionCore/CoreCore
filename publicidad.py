"""Publicidad (página propia) — portado de Santi Mens."""
from datetime import datetime, timedelta
import db
import ads
import re
from utils import formatear_moneda, limpiar_titulo_modelo

_RE_TALLE = re.compile(r'\b(XXXL|XXL|XL|L|M|S)\b', re.IGNORECASE)


def _comparar_con_periodo_anterior(access_token, advertiser_id, fecha_desde, fecha_hasta, costo, ventas, roas):
    """Variación contra el período inmediato anterior de igual largo, o None si no se pudo traer (nunca rompe la página)."""
    try:
        desde, hasta = datetime.strptime(fecha_desde, "%Y-%m-%d"), datetime.strptime(fecha_hasta, "%Y-%m-%d")
        dias = (hasta - desde).days + 1
        hasta_ant = desde - timedelta(days=1)
        desde_ant = hasta_ant - timedelta(days=dias - 1)
        campanas_ant = ads.obtener_campanas_con_metricas(access_token, advertiser_id, desde_ant.strftime("%Y-%m-%d"), hasta_ant.strftime("%Y-%m-%d"))
        costo_ant = sum(c["costo"] for c in campanas_ant)
        ventas_ant = sum(c["ventas_atribuidas"] for c in campanas_ant)
        if costo_ant <= 0 and ventas_ant <= 0:
            return None
        roas_ant = round(ventas_ant / costo_ant, 2) if costo_ant > 0 else None
        pct = lambda actual, previo: round((actual - previo) / previo * 100, 1) if previo and previo > 0 else None
        return {
            "desde": desde_ant.strftime("%d/%m"), "hasta": hasta_ant.strftime("%d/%m"),
            "costo_pct": pct(costo, costo_ant), "ventas_pct": pct(ventas, ventas_ant),
            "roas": roas_ant, "roas_diff": round(roas - roas_ant, 2) if (roas is not None and roas_ant is not None) else None,
        }
    except Exception as e:
        print(f"[Publicidad] ⚠️ No se pudo comparar con el período anterior: {e}")
        return None


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

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
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
        cursor.execute("SELECT id_meli, titulo, thumbnail FROM productos_padre")
        catalogo = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

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
            "techo": round(techo, 1),
        }

    # Embudo: impresiones → clics → ventas. Con CPC (costo por clic) y CPA (costo por venta).
    prints_total = sum(c["prints"] for c in campanas)
    ctr_general = round(clicks_total / prints_total * 100, 2) if prints_total > 0 else None
    cvr_general = round(unidades_total / clicks_total * 100, 2) if clicks_total > 0 else None
    cpc = round(costo_total / clicks_total, 2) if clicks_total > 0 else None
    cpa = round(costo_total / unidades_total, 2) if unidades_total > 0 else None

    # Mismo cálculo del período inmediato anterior (de igual largo), para decir si mejoró o empeoró.
    anterior = _comparar_con_periodo_anterior(access_token, advertiser_id, fecha_desde, fecha_hasta, costo_total, ventas_atribuidas_total, roas_general)

    # Retorno por publicación: todas las del catálogo más las que vendieron (alguna vieja puede seguir en Ads).
    ids_relevantes = list(dict.fromkeys(list(catalogo.keys()) + [r[0] for r in items_con_ventas]))
    metricas_items = ads.obtener_metricas_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_relevantes) if ids_relevantes else {}
    items_ads = []
    for id_meli, m in metricas_items.items():
        titulo_db, thumb_db = catalogo.get(id_meli, (None, None))
        roas_item = round(m["ventas"] / m["costo"], 2) if m["costo"] > 0 else None
        titulo_item = titulo_db or m["titulo"] or id_meli
        talle = _RE_TALLE.search(titulo_item)
        items_ads.append({
            "id_meli": id_meli, "titulo": titulo_item, "modelo": limpiar_titulo_modelo(titulo_item) or titulo_item,
            "talle": talle.group(0).upper() if talle else None, "thumbnail": thumb_db or m["thumbnail"],
            "costo": m["costo"], "costo_formateado": formatear_moneda(m["costo"]),
            "ventas": m["ventas"], "ventas_formateado": formatear_moneda(m["ventas"]),
            "unidades": m["unidades"], "clicks": m["clicks"], "roas": roas_item,
            "sin_ventas": m["costo"] > 0 and m["unidades"] == 0,
        })
    items_ads.sort(key=lambda i: -i["costo"])
    costo_max_item = items_ads[0]["costo"] if items_ads else 0
    for i in items_ads:
        i["pct_barra"] = max(round(i["costo"] / costo_max_item * 100), 3) if costo_max_item > 0 else 0
    items_sin_ventas = [i for i in items_ads if i["sin_ventas"]]
    items_sin_ventas_costo = sum(i["costo"] for i in items_sin_ventas)

    for c in campanas:
        c["costo_formateado"] = formatear_moneda(c["costo"])
        c["ventas_atribuidas_formateado"] = formatear_moneda(c["ventas_atribuidas"])
        c["presupuesto_formateado"] = formatear_moneda(c["presupuesto"]) if c["presupuesto"] else None
        # Una campaña que no gastó nada no tiene un ROAS "bajo": no hay retorno que medir
        c["roas_bajo"] = c["costo"] > 0 and c["roas"] is not None and c["roas"] < 3

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
        "chart_data": chart_data, "items_ads": items_ads,
        "items_sin_ventas_n": len(items_sin_ventas), "items_sin_ventas_costo_formateado": formatear_moneda(items_sin_ventas_costo),
        "prints_total": prints_total, "ctr_general": ctr_general, "cvr_general": cvr_general, "cpc": cpc, "cpa": cpa, "anterior": anterior,
        "roas_equilibrio": roas_equilibrio, "margen_sin_ads_pct": margen_sin_ads_pct, "te_deja_ganancia": te_deja_ganancia,
        "roas_slider": roas_slider,
        "pct_venta_directa": pct_venta_directa, "pct_venta_indirecta": pct_venta_indirecta,
        "venta_directa_formateada": formatear_moneda(venta_directa_total), "venta_indirecta_formateada": formatear_moneda(venta_indirecta_total),
        "pct_origen_pagado": pct_origen_pagado, "pct_origen_organico": pct_origen_organico,
        "ventas_organicas_formateada": formatear_moneda(max(facturacion_total_negocio - ventas_atribuidas_total, 0)),
    }

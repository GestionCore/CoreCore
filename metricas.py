"""
Ganancia Real — núcleo portado de Santi Mens, ahora con el desglose de
Publicidad (Ads) integrado y Reclamos/Devoluciones real (via
devoluciones_sync.py).
"""
from io import BytesIO
from psycopg.rows import dict_row
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
import db
import ads
from utils import formatear_moneda, formatear_estado_incidencia


def calcular_ganancia_real(usuario_id, cuenta_id, access_token, fecha_desde, fecha_hasta):
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT id_orden, id_meli, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, id_variante, envio_estado
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s ORDER BY fecha_venta DESC
        """, (fecha_desde, fecha_hasta))
        ventas_db = cursor.fetchall()

        cursor.execute("SELECT id_variante, talle, color FROM productos_variantes")
        # El cursor usa row_factory=dict_row (filas como {"id_variante": ...},
        # no tuplas) — indexar con r[0]/r[1] tira KeyError apenas hay alguna
        # fila. Antes nunca se notaba porque productos_variantes estaba
        # vacía (bloqueada por el bug de RLS sin política).
        info_variantes = {r["id_variante"]: (r["talle"], r["color"]) for r in cursor.fetchall()}

        cursor.execute("SELECT id_meli, precio_costo FROM productos_padre")
        # dict(cursor.fetchall()) tampoco sirve con dict_row: cada fila ya es
        # un dict de 2 claves ("id_meli", "precio_costo"), y dict() sobre una
        # lista de esos termina interpretando cada fila como el PAR
        # (clave, valor) = (nombres de columna) en vez de (id_meli, costo) —
        # no tira error, pero arma costos_por_item con basura, corrompiendo
        # el costo de fabricación de Ganancia Neta Real en silencio.
        costos_por_item = {r["id_meli"]: r["precio_costo"] for r in cursor.fetchall()}

        cursor.execute("""
            SELECT tipo, motivo, estado, id_orden, fecha, COALESCE(monto_retenido, 0.0) AS monto_retenido
            FROM incidencias_posventa WHERE fecha BETWEEN %s AND %s ORDER BY fecha DESC
        """, (fecha_desde, fecha_hasta))
        incidencias_db = cursor.fetchall()

    unidades_por_item = {}
    for v in ventas_db:
        unidades_por_item[v["id_meli"]] = unidades_por_item.get(v["id_meli"], 0) + v["cantidad"]

    # Publicidad — si no hay cuenta de anunciante o falla la consulta,
    # seguimos igual mostrando el resto de los números (nunca romper la
    # página entera por esto).
    costos_ads_por_item = {}
    ads_disponible = False
    gasto_ads_total_periodo = None
    try:
        advertiser_id = ads.obtener_advertiser_id(access_token, cuenta_id)
        if advertiser_id:
            ads_disponible = True
            ids_con_ventas = list(unidades_por_item.keys())
            costos_ads_por_item = ads.obtener_costos_ads_por_item(access_token, advertiser_id, fecha_desde, fecha_hasta, ids_con_ventas)
            gasto_ads_total_periodo = ads.obtener_gasto_ads_total_periodo(access_token, advertiser_id, fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Metricas] ⚠️ Error consultando Ads: {e}")

    ventas_procesadas = []
    total_facturado = 0.0
    total_ganancia_neta_real = 0.0
    total_costo_fabricacion = 0.0
    total_costo_ads = 0.0
    total_comision = 0.0
    total_envio_real = 0.0
    consolidado_dict = {}

    for v in ventas_db:
        id_orden, id_meli, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, id_var, envio_estado = (
            v["id_orden"], v["id_meli"], v["titulo"], v["cantidad"], v["precio_venta"],
            v["cargo_venta"], v["costo_envio"], v["fecha_venta"], v["id_variante"], v["envio_estado"]
        )
        cargo_venta = float(cargo_venta or 0.0)
        costo_envio = float(costo_envio or 0.0)

        costo_fabrica_unitario = float(costos_por_item.get(id_meli) or 0.0)
        costo_fabricacion_total = costo_fabrica_unitario * cantidad

        unidades_item = unidades_por_item.get(id_meli, 0)
        costo_ads_total_item = costos_ads_por_item.get(id_meli, 0.0)
        costo_ads_unitario = (costo_ads_total_item / unidades_item) if unidades_item > 0 else 0.0
        costo_ads_fila = round(costo_ads_unitario * cantidad, 2)

        ingreso_bruto_operacion = float(precio_venta) * cantidad
        ganancia_neta = round(ingreso_bruto_operacion - cargo_venta - costo_envio - costo_ads_fila - costo_fabricacion_total, 2)

        total_facturado += ingreso_bruto_operacion
        total_ganancia_neta_real += ganancia_neta
        total_costo_fabricacion += costo_fabricacion_total
        total_costo_ads += costo_ads_fila
        total_comision += cargo_venta
        total_envio_real += costo_envio

        talle_real, color_real = info_variantes.get(id_var, ("Único", "Único"))
        talle_str = talle_real if (not color_real or color_real == "Único") else f"{talle_real} / {color_real}"

        ventas_procesadas.append({
            "id_orden": id_orden, "id_meli": id_meli, "titulo": titulo, "talle": talle_str, "cantidad": cantidad,
            "precio_venta": formatear_moneda(ingreso_bruto_operacion), "cargo_venta": formatear_moneda(cargo_venta),
            "costo_envio": formatear_moneda(costo_envio), "envio_pendiente": (envio_estado == "pendiente"),
            "costo_ads": formatear_moneda(costo_ads_fila), "costo_fabricacion": formatear_moneda(costo_fabricacion_total),
            "ganancia_neta_formateada": formatear_moneda(ganancia_neta), "es_negativo": ganancia_neta < 0,
            "fecha": fecha_venta.strftime("%Y-%m-%d") if hasattr(fecha_venta, "strftime") else fecha_venta,
            # Numeros reales (no texto formateado) para el export a Excel.
            "raw": {
                "precio_venta": round(ingreso_bruto_operacion, 2), "cargo_venta": round(cargo_venta, 2),
                "costo_envio": round(costo_envio, 2), "costo_ads": round(costo_ads_fila, 2),
                "costo_fabricacion": round(costo_fabricacion_total, 2), "ganancia_neta": ganancia_neta,
            }
        })

        if id_meli not in consolidado_dict:
            consolidado_dict[id_meli] = {"titulo": titulo, "unidades": 0, "facturado": 0.0, "costo_fab": 0.0, "cargos_meli": 0.0, "envios": 0.0, "ads": costo_ads_total_item}
        consolidado_dict[id_meli]["unidades"] += cantidad
        consolidado_dict[id_meli]["facturado"] += ingreso_bruto_operacion
        consolidado_dict[id_meli]["costo_fab"] += costo_fabricacion_total
        consolidado_dict[id_meli]["cargos_meli"] += cargo_venta
        consolidado_dict[id_meli]["envios"] += costo_envio

    lista_consolidados = []
    for id_m, cp in consolidado_dict.items():
        u = cp["unidades"]
        p_prom = cp["facturado"] / u if u > 0 else 0.0
        c_com_u = cp["cargos_meli"] / u if u > 0 else 0.0
        c_env_u = cp["envios"] / u if u > 0 else 0.0
        c_ads_u = cp["ads"] / u if u > 0 else 0.0
        c_fab_u = cp["costo_fab"] / u if u > 0 else 0.0
        neto_u = p_prom - c_com_u - c_env_u - c_ads_u - c_fab_u
        lista_consolidados.append({
            "titulo": cp["titulo"], "unidades": u, "facturado_raw": cp["facturado"],
            "precio_promedio": formatear_moneda(p_prom), "total_facturado": formatear_moneda(cp["facturado"]),
            "cargo_u": formatear_moneda(c_com_u), "envio_u": formatear_moneda(c_env_u), "ads_u": formatear_moneda(c_ads_u),
            "costo_u": formatear_moneda(c_fab_u), "neto_u": formatear_moneda(neto_u), "neto_total": formatear_moneda(neto_u * u),
            "raw": {
                "precio_promedio": round(p_prom, 2), "total_facturado": round(cp["facturado"], 2),
                "cargo_u": round(c_com_u, 2), "envio_u": round(c_env_u, 2), "ads_u": round(c_ads_u, 2),
                "costo_u": round(c_fab_u, 2), "neto_u": round(neto_u, 2), "neto_total": round(neto_u * u, 2),
            }
        })
    lista_consolidados.sort(key=lambda c: -c["facturado_raw"])

    total_devoluciones = sum(1 for inc in incidencias_db if inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower())
    total_cancelaciones = sum(1 for inc in incidencias_db if "cancel" in (inc["tipo"] or "").lower())
    total_reclamos = sum(1 for inc in incidencias_db if inc["tipo"] in ("claim", "mediation") or "reclamo" in (inc["tipo"] or "").lower())
    total_dinero_retenido = sum(float(inc["monto_retenido"]) for inc in incidencias_db)

    conteo_motivos = {}
    for inc in incidencias_db:
        es_devolucion = inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower()
        if es_devolucion:
            motivo_legible = inc["motivo"] or "Sin motivo especificado"
            conteo_motivos[motivo_legible] = conteo_motivos.get(motivo_legible, 0) + 1
    ranking_motivos_devolucion = sorted(
        [{"motivo": m, "cantidad": c} for m, c in conteo_motivos.items()], key=lambda x: -x["cantidad"]
    )[:5]

    resumen_posventa = {
        "devoluciones": total_devoluciones, "cancelaciones": total_cancelaciones, "reclamos": total_reclamos,
        "dinero_retenido": formatear_moneda(total_dinero_retenido),
        "ranking_motivos_devolucion": ranking_motivos_devolucion,
        "lista": [
            {
                "tipo": "DEVOLUCIÓN" if (inc["tipo"] in ("returns", "return") or "devol" in (inc["tipo"] or "").lower()) else ("CANCELACIÓN" if "cancel" in (inc["tipo"] or "").lower() else "RECLAMO"),
                "motivo": inc["motivo"], "estado": formatear_estado_incidencia(inc["estado"]), "id_orden": inc["id_orden"],
                "fecha": inc["fecha"].strftime("%Y-%m-%d") if hasattr(inc["fecha"], "strftime") else inc["fecha"],
                "monto_retenido": formatear_moneda(inc["monto_retenido"]),
                "link": f"https://myaccount.mercadolibre.com.ar/sales/{inc['id_orden']}/detail"
            }
            for inc in incidencias_db
        ]
    }

    return {
        "ventas": ventas_procesadas,
        "consolidados": lista_consolidados,
        "ads_disponible": ads_disponible,
        "gasto_ads_total_periodo": gasto_ads_total_periodo,
        "posventa": resumen_posventa,
        "resumen": {
            "facturado": formatear_moneda(total_facturado),
            "ganancia_neta": formatear_moneda(total_ganancia_neta_real),
            "ganancia_neta_negativa": total_ganancia_neta_real < 0,
            "comision": formatear_moneda(total_comision),
            "envios": formatear_moneda(total_envio_real),
            "costo_ads": formatear_moneda(total_costo_ads),
            "costo_fabricacion": formatear_moneda(total_costo_fabricacion),
            # Version sin formatear (numeros de verdad, no texto "1.234,56")
            # para el export a Excel — openpyxl necesita numeros reales para
            # que las columnas se puedan sumar/graficar del lado de Excel.
            "raw": {
                "facturado": round(total_facturado, 2), "ganancia_neta": round(total_ganancia_neta_real, 2),
                "comision": round(total_comision, 2), "envios": round(total_envio_real, 2),
                "costo_ads": round(total_costo_ads, 2), "costo_fabricacion": round(total_costo_fabricacion, 2),
            }
        }
    }


def generar_excel_balance(datos, fecha_desde, fecha_hasta):
    """
    Balance de rentabilidad del período como .xlsx — item pendiente #3
    del brainstorm original. Tres hojas: Resumen (los mismos totales de
    la pantalla), Consolidado por modelo (promedio ponderado real, igual
    que en pantalla — nunca promedio simple de talles) y Detalle de
    ventas fila por fila. Devuelve un BytesIO listo para send_file.
    """
    wb = Workbook()
    azul_header = Font(bold=True, color="FFFFFF")
    fondo_header = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")

    def _armar_header(ws, columnas):
        ws.append(columnas)
        for celda in ws[1]:
            celda.font = azul_header
            celda.fill = fondo_header

    ws_resumen = wb.active
    ws_resumen.title = "Resumen"
    ws_resumen.append(["Balance de Rentabilidad — Ganancia Real"])
    ws_resumen["A1"].font = Font(bold=True, size=14)
    ws_resumen.append([f"Período: {fecha_desde} al {fecha_hasta}"])
    ws_resumen.append([])
    r = datos["resumen"]["raw"]
    _armar_header(ws_resumen, ["Concepto", "Monto ($)"])
    for etiqueta, clave in [
        ("Facturación", "facturado"), ("Cargos MeLi", "comision"), ("Envíos", "envios"),
        ("Publicidad", "costo_ads"), ("Costo de Fabricación", "costo_fabricacion"),
        ("Ganancia Neta Real", "ganancia_neta"),
    ]:
        ws_resumen.append([etiqueta, r[clave]])
    ws_resumen.append([])
    p = datos["posventa"]
    ws_resumen.append(["Devoluciones", p["devoluciones"]])
    ws_resumen.append(["Cancelaciones", p["cancelaciones"]])
    ws_resumen.append(["Reclamos", p["reclamos"]])
    ws_resumen.append(["Dinero retenido ($)", float(p["dinero_retenido"].replace(".", "").replace(",", "."))])
    for col, ancho in [("A", 26), ("B", 16)]:
        ws_resumen.column_dimensions[col].width = ancho

    ws_modelos = wb.create_sheet("Consolidado por modelo")
    _armar_header(ws_modelos, ["Modelo", "Unidades", "Precio promedio", "Facturado", "Cargo MeLi (u)", "Envío (u)", "Ads (u)", "Costo (u)", "Neto (u)", "Neto total"])
    for c in datos["consolidados"]:
        cr = c["raw"]
        ws_modelos.append([
            c["titulo"], c["unidades"], cr["precio_promedio"], cr["total_facturado"],
            cr["cargo_u"], cr["envio_u"], cr["ads_u"], cr["costo_u"], cr["neto_u"], cr["neto_total"]
        ])
    ws_modelos.column_dimensions["A"].width = 45
    for col in "BCDEFGHIJ":
        ws_modelos.column_dimensions[col].width = 15

    ws_ventas = wb.create_sheet("Detalle de ventas")
    _armar_header(ws_ventas, ["Fecha", "Orden", "Producto", "Talle", "Cantidad", "Precio venta", "Cargo MeLi", "Envío", "Ads", "Costo fabricación", "Ganancia neta"])
    for v in datos["ventas"]:
        vr = v["raw"]
        ws_ventas.append([
            v["fecha"], v["id_orden"], v["titulo"], v["talle"], v["cantidad"],
            vr["precio_venta"], vr["cargo_venta"], vr["costo_envio"], vr["costo_ads"],
            vr["costo_fabricacion"], vr["ganancia_neta"]
        ])
    ws_ventas.column_dimensions["C"].width = 45
    for col in "ABDEFGHIJK":
        ws_ventas.column_dimensions[col].width = 14

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

"""
Datos del Panel de Stock — portado de Santi Mens (SQLite single-tenant) a
Postgres multi-tenant. Los cambios reales son mínimos gracias a RLS:
- No hace falta agregar "WHERE cuenta_id = ..." a mano en cada consulta,
  la política de Row Level Security ya lo hace sola una vez que la
  conexión tiene seteado app.usuario_actual (ver db.conexion_usuario).
- Los placeholders pasan de "?" (SQLite) a "%s" (Postgres).
- El JOIN de variantes ahora es contra productos_padre.id (la clave
  propia BIGSERIAL), no contra id_meli — así quedó diseñado el esquema
  nuevo (ver 01_schema_multitenant.sql).
"""
from datetime import datetime, timedelta
import analisis_stock
import db
from utils import formatear_moneda, limpiar_titulo_modelo, normalizar_talle, rotulo_variante, ARGENTINA


def obtener_productos_y_estadisticas(usuario_id, cuenta_id=None):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        # Cursor por default (tuplas por posición) a propósito acá — todo
        # este archivo desempaqueta filas por posición, no por nombre de
        # columna, así que no hace falta (ni conviene) un row_factory de
        # diccionario.
        cursor = conexion.cursor()

        cursor.execute("""
            WITH variantes_deduplicadas AS (
                SELECT id_padre, talle, color, etiqueta, MAX(stock_propio) AS stock_propio, MAX(stock_full) AS stock_full, MAX(precio_costo) AS precio_costo
                FROM productos_variantes
                GROUP BY id_padre, talle, color, etiqueta
            )
            SELECT p.id_meli, p.titulo, p.precio, p.estado, p.thumbnail,
                   p.precio_original, p.recibis_estimado, p.cuotas_cantidad, p.cuotas_monto,
                   COALESCE(v.stock_propio, 0) AS stock_propio,
                   COALESCE(v.stock_full, 0) AS stock_full,
                   v.talle AS talle_real, v.etiqueta,
                   COALESCE(NULLIF(v.precio_costo, 0), NULLIF(p.precio_costo, 0), 0) AS costo_unitario
            FROM productos_padre p
            LEFT JOIN variantes_deduplicadas v ON v.id_padre = p.id
            ORDER BY p.titulo
        """)
        items_db = cursor.fetchall()

        hoy_dt = datetime.now(ARGENTINA)
        dias_ventana = [(hoy_dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
        # Mismo período que "Lo que tenés que reponer" (analisis_stock.VENTANA_DIAS): el gráfico usa los últimos 7 días y los "días que alcanza" toda la ventana
        fecha_desde_ritmo = (hoy_dt - timedelta(days=analisis_stock.VENTANA_DIAS)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT id_meli, fecha_venta, SUM(cantidad) FROM ventas
            WHERE fecha_venta >= %s
            GROUP BY id_meli, fecha_venta
        """, (fecha_desde_ritmo,))
        ventas_por_item_y_dia = {}
        for id_meli_v, fecha_v, cantidad_v in cursor.fetchall():
            fecha_v_str = fecha_v.strftime("%Y-%m-%d") if hasattr(fecha_v, "strftime") else fecha_v
            ventas_por_item_y_dia.setdefault(id_meli_v, {})[fecha_v_str] = cantidad_v

    modelos_agrupados = {}
    prioridad_estado = {"active": 0, "paused": 1, "closed": 2}

    for item in items_db:
        (id_meli, titulo, precio, estado, thumbnail, precio_original,
         recibis_estimado, cuotas_cantidad, cuotas_monto, stock_propio, stock_full, talle_real, etiqueta, costo_unitario) = item

        talle_detectado = normalizar_talle(talle_real)
        variante = rotulo_variante(etiqueta, talle_real)
        modelo_clave = limpiar_titulo_modelo(titulo, talle_real)

        if modelo_clave not in modelos_agrupados:
            descuento_pct = round((1 - precio / precio_original) * 100) if (precio_original and precio_original > precio) else None
            modelos_agrupados[modelo_clave] = {
                "id": id_meli, "titulo": modelo_clave, "precio": precio,
                "precio_min": precio, "precio_max": precio,
                "precio_formateado": formatear_moneda(precio),
                "precio_original_formateado": formatear_moneda(precio_original) if descuento_pct else None,
                "descuento_pct": descuento_pct,
                "recibis_formateado": formatear_moneda(recibis_estimado) if recibis_estimado else None,
                "cuotas_texto": f"{cuotas_cantidad} cuotas de ${formatear_moneda(cuotas_monto)}" if cuotas_cantidad and cuotas_monto else None,
                "estado": estado, "thumbnail": thumbnail,
                "stock_propio": 0, "stock_full": 0, "variantes": [], "_variantes_index": {},
                "historial_7d": [0] * 7, "_ids_ya_sumados_historial": set(), "unidades_ritmo": 0
            }

        m = modelos_agrupados[modelo_clave]
        if prioridad_estado.get(estado, 3) < prioridad_estado.get(m["estado"], 3):
            m["estado"] = estado

        ventas_diarias_item = ventas_por_item_y_dia.get(id_meli, {})
        if id_meli not in m["_ids_ya_sumados_historial"]:
            for idx_dia, fecha_dia in enumerate(dias_ventana):
                m["historial_7d"][idx_dia] += ventas_diarias_item.get(fecha_dia, 0)
            m["unidades_ritmo"] += sum(ventas_diarias_item.values())
            m["_ids_ya_sumados_historial"].add(id_meli)

        m["precio_min"] = min(m["precio_min"], precio)
        m["precio_max"] = max(m["precio_max"], precio)
        pausada_por_stock = (estado == 'paused' and stock_propio == 0 and stock_full == 0)

        if variante in m["_variantes_index"]:
            fila_existente = m["_variantes_index"][variante]
            if stock_propio != fila_existente["propio"] or stock_full != fila_existente["full"]:
                fila_existente["revisar_duplicado"] = True
            fila_existente["propio"] = max(fila_existente["propio"], stock_propio)
            fila_existente["costo"] = fila_existente["costo"] or float(costo_unitario or 0)
            fila_existente["full"] = max(fila_existente["full"], stock_full)
            fila_existente["pausada_por_stock"] = fila_existente["pausada_por_stock"] and pausada_por_stock
        else:
            nueva_fila = {
                "id_meli": id_meli, "talle": talle_detectado, "variante": variante, "propio": stock_propio,
                "full": stock_full, "precio": precio, "estado": estado,
                "pausada_por_stock": pausada_por_stock, "revisar_duplicado": False, "costo": float(costo_unitario or 0)
            }
            m["variantes"].append(nueva_fila)
            m["_variantes_index"][variante] = nueva_fila

    productos_lista = []
    total_activas = 0
    total_stock_propio = 0
    total_stock_full = 0
    valor_inventario_total = 0.0
    capital_a_costo, unidades_con_costo, unidades_sin_costo = 0.0, 0, 0       # lo que costó lo que hay en stock: cada variante con SU costo (la de la publicación si no tiene uno propio)

    for m in modelos_agrupados.values():
        del m["_variantes_index"]
        del m["_ids_ya_sumados_historial"]
        m["stock_propio"] = sum(v["propio"] for v in m["variantes"])
        m["stock_full"] = sum(v["full"] for v in m["variantes"])
        if m["estado"] == "active":
            total_activas += 1
            total_stock_propio += m["stock_propio"]
            total_stock_full += m["stock_full"]
            valor_inventario_total += (float(m["precio"] or 0.0) * (m["stock_propio"] + m["stock_full"]))
            for v in m["variantes"]:
                unidades = v["propio"] + v["full"]
                if v["costo"] > 0:
                    capital_a_costo += v["costo"] * unidades
                    unidades_con_costo += unidades
                else:
                    unidades_sin_costo += unidades

        if m["precio_min"] == m["precio_max"]:
            m["precio_rango"] = formatear_moneda(m["precio_min"])
        else:
            m["precio_rango"] = f"{formatear_moneda(m['precio_min'])} a {formatear_moneda(m['precio_max'])}"

        historial = m["historial_7d"]
        maximo_historial = max(historial) if max(historial) > 0 else 1
        ancho_svg, alto_svg = 70, 24
        paso_x = ancho_svg / (len(historial) - 1) if len(historial) > 1 else 0
        puntos = []
        for idx, valor in enumerate(historial):
            x = round(idx * paso_x, 1)
            y = round(alto_svg - (valor / maximo_historial) * (alto_svg - 4) - 2, 1)
            puntos.append(f"{x},{y}")
        m["sparkline_puntos"] = " ".join(puntos)
        m["sparkline_total_7d"] = sum(historial)
        del m["historial_7d"]

        # Cuántos días alcanza el stock del modelo al ritmo de las últimas semanas (solo para lo que está a la venta)
        stock_modelo = m["stock_propio"] + m["stock_full"]
        m["dias_stock"] = analisis_stock.dias_de_stock(stock_modelo, m["unidades_ritmo"]) if m["estado"] == "active" else None
        m["dias_stock_texto"], m["dias_stock_tono"] = analisis_stock.presentar_dias_de_stock(m["dias_stock"], stock_modelo) if m["estado"] == "active" else ("", "neutral")

        productos_lista.append(m)

    productos_lista.sort(key=lambda m: m["titulo"])

    reporte_global = {
        "activas": total_activas,
        "propio": total_stock_propio,
        "full": total_stock_full,
        "valor_total": formatear_moneda(valor_inventario_total),
        "capital_costo": formatear_moneda(capital_a_costo), "unidades_con_costo": unidades_con_costo, "unidades_sin_costo": unidades_sin_costo,
    }

    return productos_lista, reporte_global

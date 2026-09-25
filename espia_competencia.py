"""
Espía de Competencia — portado de Santi Mens. Sin WhatsApp bridge en
CoreLux todavía, así que el aviso de "competidor cambió de foto" queda
comentado (la DETECCIÓN sigue funcionando y quedando guardada, solo no
se manda el mensaje) — se reactiva cuando portemos ese puente.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import meli_http


def agregar_competidor(cursor, cuenta_id, id_meli_rival, alias=""):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO competidores_seguimiento (cuenta_id, id_meli_rival, alias, titulo_actual, agregado_en) VALUES (%s, %s, %s, NULL, %s)
        ON CONFLICT (cuenta_id, id_meli_rival) DO UPDATE SET alias = excluded.alias
    """, (cuenta_id, id_meli_rival.upper(), alias, ahora))


def eliminar_competidor(cursor, cuenta_id, id_meli_rival):
    cursor.execute("DELETE FROM competidores_seguimiento WHERE cuenta_id = %s AND id_meli_rival = %s", (cuenta_id, id_meli_rival.upper()))
    cursor.execute("DELETE FROM competidores_historial WHERE cuenta_id = %s AND id_meli_rival = %s", (cuenta_id, id_meli_rival.upper()))


def _consultar_rival(id_rival):
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_rival}", timeout=8)
        if resp.status_code != 200:
            return id_rival, None
        return id_rival, resp.json()
    except Exception as e:
        print(f"[Espía Competencia] ⚠️ Error consultando {id_rival}: {e}")
        return id_rival, None


def relevar_competidores(cursor, cuenta_id):
    cursor.execute("SELECT id_meli_rival FROM competidores_seguimiento WHERE cuenta_id = %s", (cuenta_id,))
    rivales = [r[0] for r in cursor.fetchall()]
    if not rivales:
        return 0

    hoy = datetime.now().strftime("%Y-%m-%d")
    relevados = 0

    # Las consultas a MeLi son independientes entre sí — se resuelven en
    # paralelo, y después se escribe todo secuencial sobre el mismo cursor
    # (mismo patrón que ads.py/metricas.py/despacho.py/sincronizador.py).
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(_consultar_rival, rivales))

    for id_rival, item in resultados:
        if item is None:
            continue
        try:
            precio = item.get("price")
            stock = item.get("available_quantity", 0)
            es_full = item.get("shipping", {}).get("logistic_type") == "fulfillment"
            sold_quantity = item.get("sold_quantity", 0)
            titulo = item.get("title")
            fotos = item.get("pictures", []) or []
            foto_principal_id = fotos[0].get("id") if fotos else None

            cursor.execute(
                "SELECT foto_principal_id FROM competidores_historial WHERE cuenta_id = %s AND id_meli_rival = %s ORDER BY fecha DESC LIMIT 1",
                (cuenta_id, id_rival)
            )
            fila_anterior = cursor.fetchone()
            foto_cambio = bool(fila_anterior and fila_anterior[0] and foto_principal_id and fila_anterior[0] != foto_principal_id)

            cursor.execute(
                "UPDATE competidores_seguimiento SET titulo_actual = %s WHERE cuenta_id = %s AND id_meli_rival = %s",
                (titulo, cuenta_id, id_rival)
            )
            cursor.execute("""
                INSERT INTO competidores_historial (cuenta_id, id_meli_rival, fecha, precio, stock_disponible, es_full, sold_quantity, foto_principal_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (cuenta_id, id_meli_rival, fecha) DO UPDATE SET
                    precio = excluded.precio, stock_disponible = excluded.stock_disponible,
                    es_full = excluded.es_full, sold_quantity = excluded.sold_quantity,
                    foto_principal_id = excluded.foto_principal_id
            """, (cuenta_id, id_rival, hoy, precio, stock, es_full, sold_quantity, foto_principal_id))

            if foto_cambio:
                print(f"[Espía Competencia] 📸 '{titulo}' ({id_rival}) cambió su foto principal.")
                # TODO: reactivar el aviso por WhatsApp cuando se porte el puente

            relevados += 1
        except Exception as e:
            print(f"[Espía Competencia] ⚠️ Error guardando {id_rival}: {e}")

    return relevados


def obtener_panorama_competencia(cursor, cuenta_id):
    cursor.execute(
        "SELECT id_meli_rival, alias, titulo_actual FROM competidores_seguimiento WHERE cuenta_id = %s ORDER BY agregado_en DESC",
        (cuenta_id,)
    )
    rivales = cursor.fetchall()

    panorama = []
    for id_rival, alias, titulo_actual in rivales:
        cursor.execute("""
            SELECT fecha, precio, stock_disponible, es_full, sold_quantity
            FROM competidores_historial WHERE cuenta_id = %s AND id_meli_rival = %s ORDER BY fecha DESC LIMIT 7
        """, (cuenta_id, id_rival))
        historial = cursor.fetchall()

        tendencia_precio = None
        if len(historial) >= 2:
            precio_hoy, precio_antes = historial[0][1], historial[-1][1]
            if precio_hoy is not None and precio_antes and precio_hoy != precio_antes:
                tendencia_precio = "bajó" if precio_hoy < precio_antes else "subió"

        panorama.append({
            "id_meli_rival": id_rival, "alias": alias or titulo_actual or id_rival, "titulo_actual": titulo_actual,
            "historial": [{"fecha": h[0].strftime("%Y-%m-%d") if hasattr(h[0], "strftime") else h[0], "precio": h[1], "stock": h[2], "es_full": bool(h[3]), "vendidos": h[4]} for h in historial],
            "tendencia_precio": tendencia_precio
        })
    return panorama

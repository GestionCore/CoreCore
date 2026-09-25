"""
Tendencias — portado de Santi Mens.

Bug de fuga entre cuentas encontrado (mismo patrón que ads.py,
facturacion.py y logistica.py): `_categoria_cache` era un único slot
global — la categoría de la PRIMERA cuenta que consultara (ej:
"Ropa y Accesorios") quedaba fija para todas las demás cuentas,
aunque vendieran otra cosa completamente distinta. Ahora se cachea
por cuenta_id.

También: tendencias_historial ahora tiene cuenta_id en su clave (según
el esquema multi-tenant), y el "INSERT OR IGNORE" de SQLite se
resuelve con "ON CONFLICT DO NOTHING" en Postgres.
"""
import re
import requests
from datetime import date, datetime, timedelta

PALABRAS_CLAVE_RUBRO = [
    "campera", "jean", "denim", "abrigo", "buzo", "hombre", "ropa", "indumentaria",
    "jacket", "chaleco", "oversize", "corderoy", "gabardina", "cargo", "nevado",
    "prelavado", "rigido", "trucker", "biker", "borrego", "vintage"
]
PALABRAS_GENERICAS_RUBRO = {
    "de", "hombre", "mujer", "jean", "denim", "campera", "chaleco", "buzo", "talle",
    "premium", "clasica", "clásica", "rigido", "rígido", "excelent", "excelente", "calce",
    "lisa", "liso", "inflable", "especial", "super", "súper", "grande", "moda", "temporada"
}
PALABRAS_RELLENO_TITULO = {"de", "para", "con", "el", "la", "los", "las", "un", "una", "y", "en"}

_categoria_cache = {}


def limpiar_titulo_modelo_local(titulo):
    t = re.sub(r'\b(talle|size)\s*[:#]?\s*(xxxl|xxl|xl|l|m|s|\d+)\b', '', titulo, flags=re.IGNORECASE)
    t = re.sub(r'\b(xxxl|xxl|xl|l|m|s)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+\d+\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def obtener_categoria_principal(access_token, cuenta_id, cursor, site_id="MLA"):
    if cuenta_id in _categoria_cache:
        return _categoria_cache[cuenta_id]["id"], _categoria_cache[cuenta_id]["nombre"]

    headers = {"Authorization": f"Bearer {access_token}"}
    cursor.execute("SELECT id_meli FROM productos_padre WHERE estado = 'active' LIMIT 1")
    fila = cursor.fetchone()
    if not fila:
        return None, None

    try:
        resp_item = requests.get(f"https://api.mercadolibre.com/items/{fila[0]}", headers=headers, timeout=8)
        if resp_item.status_code != 200:
            return None, None
        category_id = resp_item.json().get("category_id")
        if not category_id:
            return None, None

        resp_cat = requests.get(f"https://api.mercadolibre.com/categories/{category_id}", timeout=8)
        if resp_cat.status_code != 200:
            return category_id, None

        path = resp_cat.json().get("path_from_root", [])
        categoria_top = path[0] if path else {"id": category_id, "name": None}

        _categoria_cache[cuenta_id] = {"id": categoria_top.get("id"), "nombre": categoria_top.get("name")}
        return _categoria_cache[cuenta_id]["id"], _categoria_cache[cuenta_id]["nombre"]
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error detectando categoría: {e}")
        return None, None


def _armar_veredicto(presion_demanda, concentracion_top3_pct):
    """
    Traduce los números crudos a un veredicto en texto plano — "¿vale
    la pena meterse acá?". Los umbrales son heurísticas declaradas
    (no una ciencia exacta): mejor ser honesto con eso que fingir una
    precisión que la muestra no tiene.
    """
    if presion_demanda >= 5:
        demanda_texto, demanda_nivel = "Alta demanda por publicación", "alta"
    elif presion_demanda >= 1:
        demanda_texto, demanda_nivel = "Demanda moderada", "media"
    else:
        demanda_texto, demanda_nivel = "Demanda baja o muy repartida", "baja"

    if concentracion_top3_pct is not None and concentracion_top3_pct >= 50:
        saturacion_texto, saturacion_nivel = "Concentrado en pocos vendedores — más difícil de romper salvo que ofrezcas algo distinto", "alta"
    elif concentracion_top3_pct is not None and concentracion_top3_pct >= 25:
        saturacion_texto, saturacion_nivel = "Medianamente repartido entre varios vendedores", "media"
    else:
        saturacion_texto, saturacion_nivel = "Fragmentado — hay lugar para entrar sin pelear contra 2-3 gigantes", "baja"

    if demanda_nivel == "alta" and saturacion_nivel == "baja":
        resumen = "Buena señal: se vende bien y no está copado de competidores grandes."
    elif demanda_nivel == "alta" and saturacion_nivel == "alta":
        resumen = "Se vende, pero pocos vendedores se llevan la mayoría — entrar requiere diferenciarte, no solo bajar precio."
    elif demanda_nivel == "baja" and saturacion_nivel == "baja":
        resumen = "Poca pelea, pero también poca demanda comprobada — nicho chico, no necesariamente malo."
    else:
        resumen = "Mercado mixto — conviene mirar precio, marcas y tu propio margen antes de decidir."

    return {
        "demanda_texto": demanda_texto, "demanda_nivel": demanda_nivel,
        "saturacion_texto": saturacion_texto, "saturacion_nivel": saturacion_nivel,
        "resumen": resumen,
        "nota": "Estimado sobre una muestra de hasta 50 publicaciones — no es el dataset completo del mercado.",
    }


def explorar_demanda(access_token, termino=None, category_id=None, site_id="MLA", limite=50):
    """
    Buscador/explorador de demanda real — reemplaza la dependencia del
    endpoint /trends, que MeLi viene devolviendo 404 "Not found public
    trends" (un límite de la API, no un bug de acá: ni con category_id
    devuelve datos para muchas cuentas/categorías).

    En vez de eso, usa /sites/{site}/search — el buscador público de
    MeLi, estable y sin permisos especiales — para armar una foto real
    de demanda: cuánta competencia hay, cuánto se está vendiendo
    (sold_quantity de los resultados, como proxy de demanda), en qué
    rango de precio, cuán concentrado está entre pocos vendedores, y
    un veredicto en texto plano.

    Acepta termino (búsqueda libre) O category_id (para navegar
    cualquier rama de MeLi y evaluar un nicho nuevo, no solo lo que ya
    vendés) — al menos uno de los dos es obligatorio.
    """
    termino = (termino or "").strip()
    if not termino and not category_id:
        return None

    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    params = {"limit": limite}
    if category_id:
        params["category"] = category_id
    if termino:
        params["q"] = termino
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/sites/{site_id}/search",
            headers=headers, params=params, timeout=10
        )
        if resp.status_code != 200:
            return {"termino": termino, "error": f"MeLi devolvió {resp.status_code} — probá con otro término o categoría."}
    except Exception as e:
        return {"termino": termino, "error": f"Error de conexión: {e}"}

    data = resp.json()
    resultados = data.get("results", []) or []
    if not resultados:
        return {"termino": termino, "error": "No se encontraron publicaciones para esta búsqueda."}

    precios = [r.get("price") for r in resultados if r.get("price")]
    ventas_muestra_lista = [r.get("sold_quantity") or 0 for r in resultados]
    ventas_totales_muestra = sum(ventas_muestra_lista)
    total_publicaciones = (data.get("paging", {}) or {}).get("total", len(resultados))

    ventas_por_vendedor = {}
    for r in resultados:
        vendedor = (r.get("seller") or {}).get("nickname") or str((r.get("seller") or {}).get("id") or "Desconocido")
        ventas_por_vendedor[vendedor] = ventas_por_vendedor.get(vendedor, 0) + (r.get("sold_quantity") or 0)
    ranking_vendedores = sorted(ventas_por_vendedor.items(), key=lambda x: -x[1])[:5]

    concentracion_top3_pct = None
    if ventas_totales_muestra > 0:
        top3 = sum(v for _, v in sorted(ventas_por_vendedor.items(), key=lambda x: -x[1])[:3])
        concentracion_top3_pct = round((top3 / ventas_totales_muestra) * 100, 1)

    presion_demanda = round(ventas_totales_muestra / total_publicaciones, 2) if total_publicaciones else 0.0

    marcas_distintas = None
    for filtro in (data.get("available_filters") or []):
        if filtro.get("id") == "BRAND":
            marcas_distintas = len(filtro.get("values") or [])
            break

    distribucion_precios = []
    if precios:
        p_min, p_max = min(precios), max(precios)
        if p_max > p_min:
            ancho = (p_max - p_min) / 5
            for i in range(5):
                desde = p_min + ancho * i
                hasta = p_min + ancho * (i + 1)
                cantidad = sum(1 for p in precios if desde <= p <= hasta) if i == 4 else sum(1 for p in precios if desde <= p < hasta)
                distribucion_precios.append({"desde": round(desde), "hasta": round(hasta), "cantidad": cantidad})
        else:
            distribucion_precios.append({"desde": round(p_min), "hasta": round(p_max), "cantidad": len(precios)})

    top_publicaciones = sorted(resultados, key=lambda r: -(r.get("sold_quantity") or 0))[:10]

    return {
        "termino": termino, "category_id": category_id,
        "total_publicaciones": total_publicaciones,
        "ventas_totales_muestra": ventas_totales_muestra,
        "precio_minimo": min(precios) if precios else None,
        "precio_promedio": round(sum(precios) / len(precios), 2) if precios else None,
        "precio_maximo": max(precios) if precios else None,
        "vendedores_distintos": len(ventas_por_vendedor),
        "concentracion_top3_pct": concentracion_top3_pct,
        "presion_demanda": presion_demanda,
        "marcas_distintas": marcas_distintas,
        "distribucion_precios": distribucion_precios,
        "veredicto": _armar_veredicto(presion_demanda, concentracion_top3_pct),
        "top_publicaciones": [
            {"titulo": r.get("title"), "precio": r.get("price"), "vendidas": r.get("sold_quantity") or 0,
             "permalink": r.get("permalink"), "thumbnail": (r.get("thumbnail") or "").replace("http://", "https://")}
            for r in top_publicaciones
        ],
        "ranking_vendedores": [{"nombre": n, "vendidas": v} for n, v in ranking_vendedores],
    }


def estimar_margen_categoria(access_token, category_id, precio_referencia, costo_fabricacion=None):
    """
    Cruza el precio promedio de una categoría/búsqueda con la comisión
    REAL de MeLi para esa categoría (misma fuente que la Calculadora de
    Comisiones) y, si el usuario tipea un costo de fabricación
    estimado, con la ganancia neta esperada. Ni Nubimetrics ni Real
    Trends pueden hacer este cruce — no tienen tu estructura de costos.
    """
    import calculadora_costos
    if not category_id or not precio_referencia or precio_referencia <= 0:
        return None
    desglose = calculadora_costos.calcular_desglose_real(access_token, precio_referencia, category_id, "gold_special", ofrece_cuotas=False)
    if not desglose or "error" in desglose:
        return None

    resultado = {
        "precio_referencia": precio_referencia,
        "comision_estimada": desglose.get("comision_total"),
        "costo_envio_estimado": desglose.get("costo_envio"),
        "recibis_estimado": desglose.get("recibis"),
        "ganancia_neta_estimada": None, "margen_pct_estimado": None,
    }
    if costo_fabricacion is not None and costo_fabricacion > 0 and resultado["recibis_estimado"] is not None:
        ganancia_neta = resultado["recibis_estimado"] - costo_fabricacion
        resultado["ganancia_neta_estimada"] = round(ganancia_neta, 2)
        resultado["margen_pct_estimado"] = round((ganancia_neta / precio_referencia) * 100, 1)
    return resultado


def obtener_categorias_raiz(site_id="MLA"):
    """Categorías de primer nivel de MeLi — punto de partida para navegar ramas de cualquier rubro, no solo el propio."""
    try:
        resp = requests.get(f"https://api.mercadolibre.com/sites/{site_id}/categories", timeout=8)
        if resp.status_code != 200:
            return []
        return [{"id": c["id"], "nombre": c["name"]} for c in resp.json()]
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error trayendo categorías raíz: {e}")
        return []


def obtener_rama_categoria(category_id):
    """Subcategorías + camino (breadcrumb) de una categoría — para ir bajando ramas dentro de un rubro."""
    try:
        resp = requests.get(f"https://api.mercadolibre.com/categories/{category_id}", timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "id": data.get("id"), "nombre": data.get("name"),
            "camino": [{"id": p["id"], "nombre": p["name"]} for p in (data.get("path_from_root") or [])],
            "subcategorias": [
                {"id": h["id"], "nombre": h["name"], "cantidad_publicaciones": h.get("total_items_in_this_category")}
                for h in (data.get("children_categories") or [])
            ],
        }
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error trayendo la categoría {category_id}: {e}")
        return None


# ============================================================
# Seguimiento de tendencias — construye un historial REAL en el
# tiempo (nadie más lo tiene: Real Trends solo pone una flechita de
# ">20%", nosotros guardamos snapshots de verdad). Arranca vacío por
# cuenta y se va llenando con el uso, nunca se inventa historial.
# ============================================================

def agregar_seguimiento(cursor, cuenta_id, tipo, valor, etiqueta, automatico=False):
    if tipo not in ("termino", "categoria"):
        return None
    cursor.execute("""
        INSERT INTO tendencias_seguimiento (cuenta_id, tipo, valor, etiqueta, automatico)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (cuenta_id, tipo, valor) DO UPDATE SET etiqueta = excluded.etiqueta
        RETURNING id
    """, (cuenta_id, tipo, valor, etiqueta, automatico))
    return cursor.fetchone()[0]


def eliminar_seguimiento(cursor, cuenta_id, seguimiento_id):
    # A propósito no se puede borrar el seguimiento automático de la
    # categoría principal desde acá — se recalcula solo si el usuario
    # cambia de rubro.
    cursor.execute(
        "DELETE FROM tendencias_seguimiento WHERE cuenta_id = %s AND id = %s AND automatico = false",
        (cuenta_id, seguimiento_id)
    )
    return cursor.rowcount > 0


def asegurar_seguimiento_categoria_principal(cursor, cuenta_id, category_id, category_nombre):
    if not category_id:
        return
    agregar_seguimiento(cursor, cuenta_id, "categoria", category_id, category_nombre or category_id, automatico=True)


def _tomar_snapshot(access_token, seguimiento, site_id="MLA"):
    """Una sola consulta a MeLi — devuelve los números del día para un seguimiento, sin tocar la base."""
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    params = {"limit": 50}
    if seguimiento["tipo"] == "categoria":
        params["category"] = seguimiento["valor"]
    else:
        params["q"] = seguimiento["valor"]
    try:
        resp = requests.get(f"https://api.mercadolibre.com/sites/{site_id}/search", headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        resultados = data.get("results", []) or []
        precios = [r.get("price") for r in resultados if r.get("price")]
        ventas = sum(r.get("sold_quantity") or 0 for r in resultados)
        vendedores = {(r.get("seller") or {}).get("id") for r in resultados if (r.get("seller") or {}).get("id")}
        total_pub = (data.get("paging", {}) or {}).get("total", len(resultados))
        return {
            "total_publicaciones": total_pub, "ventas_muestra": ventas,
            "precio_promedio": round(sum(precios) / len(precios), 2) if precios else None,
            "vendedores_distintos": len(vendedores),
        }
    except Exception as e:
        print(f"[Tendencias] ⚠️ Error tomando snapshot de '{seguimiento.get('etiqueta')}': {e}")
        return None


def relevar_snapshots_tendencias(access_token, cursor, cuenta_id, site_id="MLA"):
    """
    Corre una vez por día (scheduler) — toma un snapshot de HOY para
    cada término/categoría que la cuenta sigue. UPSERT por fecha, así
    una corrida repetida el mismo día no duplica ni pisa con un dato
    peor si ya se tomó temprano.
    """
    cursor.execute("SELECT id, tipo, valor, etiqueta FROM tendencias_seguimiento WHERE cuenta_id = %s", (cuenta_id,))
    seguimientos = [{"id": r[0], "tipo": r[1], "valor": r[2], "etiqueta": r[3]} for r in cursor.fetchall()]
    if not seguimientos:
        return 0

    hoy = datetime.now().strftime("%Y-%m-%d")
    relevados = 0
    for s in seguimientos:
        datos = _tomar_snapshot(access_token, s, site_id)
        if not datos:
            continue
        cursor.execute("""
            INSERT INTO tendencias_snapshots (cuenta_id, seguimiento_id, fecha, total_publicaciones, ventas_muestra, precio_promedio, vendedores_distintos)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (cuenta_id, seguimiento_id, fecha) DO UPDATE SET
                total_publicaciones = excluded.total_publicaciones, ventas_muestra = excluded.ventas_muestra,
                precio_promedio = excluded.precio_promedio, vendedores_distintos = excluded.vendedores_distintos
        """, (cuenta_id, s["id"], hoy, datos["total_publicaciones"], datos["ventas_muestra"], datos["precio_promedio"], datos["vendedores_distintos"]))
        relevados += 1
    return relevados


def listar_seguimientos_con_historial(cursor, cuenta_id, dias=60):
    cursor.execute("""
        SELECT id, tipo, valor, etiqueta, automatico FROM tendencias_seguimiento
        WHERE cuenta_id = %s ORDER BY automatico DESC, agregado_en DESC
    """, (cuenta_id,))
    seguimientos = cursor.fetchall()
    if not seguimientos:
        return []

    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    resultado = []
    for sid, tipo, valor, etiqueta, automatico in seguimientos:
        cursor.execute("""
            SELECT fecha, total_publicaciones, ventas_muestra, precio_promedio
            FROM tendencias_snapshots WHERE seguimiento_id = %s AND fecha >= %s ORDER BY fecha ASC
        """, (sid, desde))
        historial = cursor.fetchall()
        serie = [
            {"fecha": f.strftime("%Y-%m-%d") if hasattr(f, "strftime") else f, "publicaciones": p, "ventas": v,
             "precio_promedio": float(pp) if pp is not None else None}
            for f, p, v, pp in historial
        ]
        tendencia_pct = None
        if len(serie) >= 2 and serie[0]["ventas"]:
            tendencia_pct = round(((serie[-1]["ventas"] - serie[0]["ventas"]) / serie[0]["ventas"]) * 100, 1)
        resultado.append({
            "id": sid, "tipo": tipo, "valor": valor, "etiqueta": etiqueta, "automatico": automatico,
            "serie": serie, "tendencia_pct": tendencia_pct, "tiene_historial_suficiente": len(serie) >= 2,
        })
    return resultado


def detectar_movimiento_categoria_principal(cursor, cuenta_id, umbral_pct=15):
    """Para la alerta proactiva en Logros — solo dispara si el movimiento entre los últimos 2 snapshots es significativo."""
    cursor.execute("""
        SELECT id, etiqueta FROM tendencias_seguimiento
        WHERE cuenta_id = %s AND automatico = true AND tipo = 'categoria' LIMIT 1
    """, (cuenta_id,))
    fila = cursor.fetchone()
    if not fila:
        return None
    seguimiento_id, etiqueta = fila

    cursor.execute("""
        SELECT fecha, ventas_muestra FROM tendencias_snapshots
        WHERE seguimiento_id = %s ORDER BY fecha DESC LIMIT 2
    """, (seguimiento_id,))
    filas = cursor.fetchall()
    if len(filas) < 2:
        return None

    (_, ventas_ultima), (_, ventas_anterior) = filas
    if not ventas_anterior:
        return None
    variacion = ((ventas_ultima - ventas_anterior) / ventas_anterior) * 100
    if abs(variacion) < umbral_pct:
        return None
    return {"categoria": etiqueta, "variacion_pct": round(variacion, 1), "subio": variacion > 0}


def obtener_tendencias(access_token, site_id="MLA", category_id=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/trends/{site_id}"
    if category_id:
        url += f"/{category_id}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[Tendencias] ⚠️ Error consultando tendencias: {resp.status_code} - {resp.text[:200]}")
            return []
        lista = resp.json()
        for idx, t in enumerate(lista):
            kw = t.get("keyword", "").lower()
            t["relevante"] = True if category_id else any(p in kw for p in PALABRAS_CLAVE_RUBRO)
            t["posicion"] = idx + 1
            t["es_top"] = idx < 20 and t["relevante"]
        return lista
    except Exception as e:
        print(f"[Tendencias] ❌ Error de conexión: {e}")
        return []


def cruzar_tendencias_con_competencia(tendencias_relevantes, cursor):
    cursor.execute("SELECT alias, titulo_actual FROM competidores_seguimiento WHERE titulo_actual IS NOT NULL")
    rivales = cursor.fetchall()
    if not rivales:
        return []
    resultado = []
    for t in tendencias_relevantes:
        if t.get("es_oportunidad"):
            kw = t.get("keyword", "").lower()
            rivales_que_la_usan = [alias or "un competidor" for alias, titulo in rivales if kw in (titulo or "").lower()]
            if rivales_que_la_usan:
                resultado.append({"keyword": t["keyword"], "rivales": rivales_que_la_usan})
    return resultado


def _enesimo_dia_semana_del_mes(anio, mes, dia_semana, n):
    d = date(anio, mes, 1)
    primeros = (dia_semana - d.weekday()) % 7
    primer = d + timedelta(days=primeros)
    return primer + timedelta(weeks=n - 1)


def _enesimo_domingo_del_mes(anio, mes, n):
    return _enesimo_dia_semana_del_mes(anio, mes, 6, n)


def obtener_calendario_estacional(anio=None):
    if anio is None:
        anio = datetime.now().year
    eventos = [
        {"nombre": "Vuelta al cole", "fecha": date(anio, 2, 25), "categoria_sugerida": "buzos, abrigos livianos"},
        {"nombre": "Día de la Primavera / Amistad", "fecha": date(anio, 9, 21), "categoria_sugerida": "prendas de entretiempo"},
        {"nombre": "Día del Padre", "fecha": _enesimo_domingo_del_mes(anio, 6, 3), "categoria_sugerida": "camperas, ropa de abrigo para hombre"},
        {"nombre": "Día de la Madre", "fecha": _enesimo_domingo_del_mes(anio, 10, 3), "categoria_sugerida": "indumentaria en general"},
        {"nombre": "Día del Niño", "fecha": _enesimo_domingo_del_mes(anio, 8, 2), "categoria_sugerida": "ropa infantil si aplica"},
        {"nombre": "Black Friday", "fecha": _enesimo_dia_semana_del_mes(anio, 11, 3, 4) + timedelta(days=1), "categoria_sugerida": "todo el catálogo — el pico de ventas más grande del año"},
        {"nombre": "Navidad", "fecha": date(anio, 12, 25), "categoria_sugerida": "regalos, indumentaria de temporada"},
    ]
    hoy = date.today()
    for e in eventos:
        e["fecha_str"] = e["fecha"].strftime("%d/%m/%Y")
        e["dias_faltantes"] = (e["fecha"] - hoy).days
        e["ya_paso"] = e["dias_faltantes"] < 0
    eventos = [e for e in eventos if not e["ya_paso"]]
    eventos.sort(key=lambda e: e["dias_faltantes"])
    return eventos


def cruzar_tendencias_con_catalogo(tendencias_relevantes, cursor):
    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active' ORDER BY titulo")
    activos = cursor.fetchall()
    if not activos:
        return []
    titulos_concatenados = " ".join(t.lower() for _, t in activos)
    oportunidades = []
    for t in tendencias_relevantes:
        termino = t.get("keyword", "").strip()
        if not termino or termino.lower() in titulos_concatenados:
            continue
        id_meli_sugerido, titulo_actual = activos[0]
        titulo_sugerido = f"{titulo_actual} {termino}"[:60]
        oportunidades.append({"termino": termino, "id_meli_sugerido": id_meli_sugerido, "titulo_actual": titulo_actual, "titulo_sugerido": titulo_sugerido})
    return oportunidades[:5]


def registrar_y_detectar_emergentes(cursor, cuenta_id, keywords_de_hoy):
    hoy = datetime.now().strftime("%Y-%m-%d")
    hace_14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    cursor.execute("SELECT DISTINCT keyword FROM tendencias_historial WHERE cuenta_id = %s AND fecha >= %s AND fecha < %s", (cuenta_id, hace_14, hoy))
    vistas_antes = {r[0] for r in cursor.fetchall()}

    for kw in keywords_de_hoy:
        cursor.execute("INSERT INTO tendencias_historial (cuenta_id, keyword, fecha) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (cuenta_id, kw, hoy))

    hace_30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM tendencias_historial WHERE cuenta_id = %s AND fecha < %s", (cuenta_id, hace_30))

    return {kw for kw in keywords_de_hoy if kw not in vistas_antes}


def calcular_seo_score_titulo(titulo, palabras_tendencia_actuales):
    score = 100
    razones = []
    palabras_titulo = set(p.lower() for p in titulo.split() if p.lower() not in PALABRAS_RELLENO_TITULO)
    longitud = len(titulo)

    if longitud < 40:
        resta = 15
        score -= resta
        razones.append(f"-{resta}: título corto ({longitud} caracteres) — MeLi permite hasta 60, estás dejando espacio de búsqueda sin usar")
    elif longitud > 60:
        resta = 10
        score -= resta
        razones.append(f"-{resta}: título de {longitud} caracteres — MeLi lo trunca en la búsqueda a partir de los 60")

    tiene_rubro = any(p in PALABRAS_CLAVE_RUBRO for p in palabras_titulo)
    if not tiene_rubro:
        resta = 20
        score -= resta
        razones.append(f"-{resta}: no menciona ninguna palabra clave típica del rubro")

    tiene_talle = any(t in titulo.upper().split() for t in ["S", "M", "L", "XL", "XXL", "XXXL"])
    if not tiene_talle:
        razones.append("Tip: agregar el talle en el título no suma puntos de SEO en sí, pero ayuda a la conversión")

    palabras_tendencia_en_titulo = palabras_titulo & palabras_tendencia_actuales
    if palabras_tendencia_en_titulo:
        bonus = min(len(palabras_tendencia_en_titulo) * 10, 20)
        score += bonus
        razones.append(f"+{bonus}: incluye {len(palabras_tendencia_en_titulo)} palabra(s) que están en tendencia esta semana")

    score = max(0, min(100, score))
    return {"score": score, "razones": razones}


def calcular_seo_scores_catalogo(cursor, tendencias_relevantes):
    palabras_tendencia = set()
    for t in tendencias_relevantes:
        palabras_tendencia.update(p.lower() for p in t.get("keyword", "").split())

    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active'")
    resultados = []
    vistos = set()
    for id_meli, titulo in cursor.fetchall():
        clave_modelo = limpiar_titulo_modelo_local(titulo)
        if clave_modelo in vistos:
            continue
        vistos.add(clave_modelo)
        analisis = calcular_seo_score_titulo(titulo, palabras_tendencia)
        resultados.append({"id_meli": id_meli, "titulo": titulo, "score": analisis["score"], "razones": analisis["razones"]})
    resultados.sort(key=lambda r: r["score"])
    return resultados


def detectar_canibalismo(cursor):
    cursor.execute("SELECT id_meli, titulo FROM productos_padre WHERE estado = 'active'")
    filas = cursor.fetchall()
    if len(filas) < 2:
        return []

    modelos = {}
    for id_meli, titulo in filas:
        clave = limpiar_titulo_modelo_local(titulo)
        if clave not in modelos:
            palabras = {p for p in clave.lower().split() if len(p) > 2 and p not in PALABRAS_GENERICAS_RUBRO}
            modelos[clave] = {"id_referencia": id_meli, "palabras": palabras}

    claves = list(modelos.keys())
    pares_sospechosos = []
    for i in range(len(claves)):
        for j in range(i + 1, len(claves)):
            a, b = modelos[claves[i]], modelos[claves[j]]
            if not a["palabras"] or not b["palabras"]:
                continue
            interseccion = a["palabras"] & b["palabras"]
            union = a["palabras"] | b["palabras"]
            similitud = len(interseccion) / len(union) if union else 0
            if similitud >= 0.6 and len(interseccion) >= 2:
                pares_sospechosos.append({
                    "modelo_a": claves[i], "id_a": a["id_referencia"], "modelo_b": claves[j], "id_b": b["id_referencia"],
                    "palabras_compartidas": sorted(interseccion), "similitud_pct": round(similitud * 100)
                })
    pares_sospechosos.sort(key=lambda x: -x["similitud_pct"])
    return pares_sospechosos[:8]

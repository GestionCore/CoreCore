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

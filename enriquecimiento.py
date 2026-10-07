"""
Datos extra de cada publicación que ofrece la API de Mercado Libre y que se completan de a poco, en segundo plano.

Cada pasada del sync procesa un lote chico (las publicaciones más desactualizadas primero) para no pasarse del límite de la API, así
que una cuenta con muchas publicaciones se va completando sola. Las pantallas leen siempre de la base, nunca esperan a la API.

  calidad   GET /item/{id}/performance                    puntaje 0-100 y qué mejorar (con el link directo para editar)
  visitas   GET /items/{id}/visits/time_window            visitas de los últimos 14 días y de los 14 anteriores
  full      GET /inventories/{inventory_id}/stock/fulfillment   unidades no disponibles en FULL (dañadas, perdidas, en tránsito...)
  catalogo  GET /items/{id}/price_to_win                  solo publicaciones de catálogo: si ganan, comparten o pierden el primer lugar
  opiniones GET /reviews/item/{id}                        calificación, distribución de estrellas, atributos y las opiniones críticas

Cada una es best-effort: un error no frena el sync ni toca lo que ya había.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import db
import meli_http
from utils import hoy_argentina

SITE_ID = "MLA"
HILOS = 6
HORAS = {"calidad": 24, "visitas": 6, "full": 6, "catalogo": 3, "opiniones": 24}
TOPE = {"calidad": 25, "visitas": 25, "full": 20, "catalogo": 20, "opiniones": 12}


def _pendientes(cursor, cuenta_id, columna_en, horas, condicion, tope, columnas="id_meli"):
    # `columna_en`, `condicion` y `columnas` son constantes de este módulo, nunca texto del usuario
    cursor.execute(f"""
        SELECT {columnas} FROM productos_padre
        WHERE cuenta_id = %s AND estado IN ('active', 'paused') {condicion}
          AND ({columna_en} IS NULL OR {columna_en} < now() - make_interval(hours => %s))
        ORDER BY {columna_en} NULLS FIRST LIMIT %s
    """, (cuenta_id, horas, tope))
    return cursor.fetchall()


def _en_paralelo(funcion, items):
    with ThreadPoolExecutor(max_workers=HILOS) as pool:
        return list(pool.map(funcion, items))


# ── Calidad de la publicación ──────────────────────────────────────────────

def acciones_de_calidad(performance):
    """Lo que MeLi pide mejorar: una entrada por regla pendiente, con el texto de MeLi y el link directo para resolverla."""
    acciones = []
    for bucket in performance.get("buckets", []):
        for variable in bucket.get("variables", []):
            for regla in variable.get("rules", []):
                if regla.get("status") == "COMPLETED":
                    continue
                w = regla.get("wordings") or {}
                acciones.append({
                    "clave": regla.get("key"), "grupo": bucket.get("title"), "variable": variable.get("title"),
                    "texto": w.get("title") or variable.get("title"), "boton": w.get("label"), "link": w.get("link"),
                    "modo": regla.get("mode"),
                })
    return acciones


def refrescar_calidad(usuario_id, cuenta_id, access_token, tope=TOPE["calidad"]):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        ids = [r[0] for r in _pendientes(conexion.cursor(), cuenta_id, "calidad_en", HORAS["calidad"], "", tope)]
    if not ids:
        return 0
    headers = {"Authorization": f"Bearer {access_token}"}

    def _uno(item_id):
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/item/{item_id}/performance", headers=headers, timeout=10)
            return item_id, (resp.json() if resp.status_code == 200 else None)
        except Exception:
            return item_id, None

    resultados = _en_paralelo(_uno, ids)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for item_id, d in resultados:
            if d:
                cursor.execute("""UPDATE productos_padre SET calidad_score = %s, calidad_nivel = %s, calidad_acciones = %s::jsonb, calidad_en = now()
                                  WHERE cuenta_id = %s AND id_meli = %s""",
                               (d.get("score"), d.get("level"), json.dumps(acciones_de_calidad(d)), cuenta_id, item_id))
            else:   # sin dato (publicación cerrada, error): se marca como intentada para no reintentar en cada pasada
                cursor.execute("UPDATE productos_padre SET calidad_en = now() WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, item_id))
    return len(ids)


# ── Visitas ────────────────────────────────────────────────────────────────

def refrescar_visitas(usuario_id, cuenta_id, access_token, tope=TOPE["visitas"]):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        ids = [r[0] for r in _pendientes(conexion.cursor(), cuenta_id, "visitas_en", HORAS["visitas"], "", tope)]
    if not ids:
        return 0
    headers = {"Authorization": f"Bearer {access_token}"}
    corte = hoy_argentina() - timedelta(days=14)

    def _uno(item_id):
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/items/{item_id}/visits/time_window?last=28&unit=day", headers=headers, timeout=10)
            if resp.status_code != 200:
                return item_id, None
            recientes = previas = 0
            for dia in resp.json().get("results", []):
                fecha = datetime.fromisoformat(str(dia["date"]).replace("Z", "+00:00")).date()
                if fecha >= corte:
                    recientes += int(dia.get("total") or 0)
                else:
                    previas += int(dia.get("total") or 0)
            return item_id, (recientes, previas)
        except Exception:
            return item_id, None

    resultados = _en_paralelo(_uno, ids)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for item_id, v in resultados:
            if v:
                cursor.execute("UPDATE productos_padre SET visitas_14d = %s, visitas_previas_14d = %s, visitas_en = now() WHERE cuenta_id = %s AND id_meli = %s",
                               (v[0], v[1], cuenta_id, item_id))
            else:
                cursor.execute("UPDATE productos_padre SET visitas_en = now() WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, item_id))
    return len(ids)


# ── Stock de FULL: unidades no disponibles ─────────────────────────────────

def refrescar_full(usuario_id, cuenta_id, access_token, tope=TOPE["full"]):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        filas = _pendientes(conexion.cursor(), cuenta_id, "full_en", HORAS["full"], "AND inventory_id IS NOT NULL", tope, columnas="id_meli, inventory_id")
    if not filas:
        return 0
    headers = {"Authorization": f"Bearer {access_token}"}

    def _uno(fila):
        item_id, inventory_id = fila
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/inventories/{inventory_id}/stock/fulfillment", headers=headers, timeout=10)
            if resp.status_code != 200:
                return item_id, None
            d = resp.json()
            return item_id, (int(d.get("not_available_quantity") or 0), d.get("not_available_detail") or [])
        except Exception:
            return item_id, None

    resultados = _en_paralelo(_uno, filas)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for item_id, r in resultados:
            if r:
                cursor.execute("UPDATE productos_padre SET full_no_disponible = %s, full_detalle = %s::jsonb, full_en = now() WHERE cuenta_id = %s AND id_meli = %s",
                               (r[0], json.dumps(r[1]), cuenta_id, item_id))
            else:
                cursor.execute("UPDATE productos_padre SET full_en = now() WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, item_id))
    return len(filas)


# ── Catálogo: precio para ganar ────────────────────────────────────────────

def refrescar_catalogo(usuario_id, cuenta_id, access_token, tope=TOPE["catalogo"]):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        ids = [r[0] for r in _pendientes(conexion.cursor(), cuenta_id, "catalogo_en", HORAS["catalogo"], "AND catalog_product_id IS NOT NULL", tope)]
    if not ids:
        return 0
    headers = {"Authorization": f"Bearer {access_token}"}

    def _uno(item_id):
        try:
            resp = meli_http.get(f"https://api.mercadolibre.com/items/{item_id}/price_to_win?siteId={SITE_ID}&version=v2", headers=headers, timeout=10)
            if resp.status_code != 200:
                return item_id, None
            d = resp.json()
            return item_id, (d.get("status"), precio_para_ganar(d.get("price_to_win")), detalle_catalogo(d))
        except Exception:
            return item_id, None

    resultados = _en_paralelo(_uno, ids)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for item_id, r in resultados:
            if r:
                cursor.execute("UPDATE productos_padre SET catalogo_estado = %s, catalogo_precio_para_ganar = %s, catalogo_detalle = %s::jsonb, catalogo_en = now() "
                               "WHERE cuenta_id = %s AND id_meli = %s", (r[0], r[1], json.dumps(r[2]), cuenta_id, item_id))
            else:
                cursor.execute("UPDATE productos_padre SET catalogo_en = now() WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, item_id))
    return len(ids)


def precio_para_ganar(valor):
    """
    El número que se guarda en catalogo_precio_para_ganar. Mercado Libre informa `price_to_win` como un número, pero si algún día lo manda como un
    objeto con reglas (un monto por condición) un float(dict) rompería la actualización de TODO el lote: acá se toma el monto principal o se deja en None
    (el detalle completo queda igual en catalogo_detalle).
    """
    if isinstance(valor, dict):
        valor = valor.get("price") if valor.get("price") is not None else valor.get("amount")
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def detalle_catalogo(d):
    """Lo que vale la pena guardar de la respuesta de price_to_win: no el JSON entero (puede traer datos de otros vendedores), solo lo que se usa."""
    ganador = d.get("winner") if isinstance(d.get("winner"), dict) else None
    campos = {
        "price_to_win": d.get("price_to_win"), "status": d.get("status"), "visit_share": d.get("visit_share"),
        "competitors_sharing_first_place": d.get("competitors_sharing_first_place"), "boosts": d.get("boosts"),
        "winner": {"price": ganador.get("price"), "boosts": ganador.get("boosts")} if ganador else None,
    }
    return {k: v for k, v in campos.items() if v is not None}


def _opinion_critica(r):
    return {"estrellas": r.get("rate"), "titulo": (r.get("title") or "")[:120], "texto": (r.get("content") or "")[:400],
            "fecha": (r.get("date_created") or "")[:10]}


def datos_de_opiniones(item_id, headers):
    """
    Lo que Mercado Libre sabe de las opiniones de una publicación, o None si no respondió. Las publicaciones de un mismo modelo
    (todos sus talles o variantes) comparten opiniones y tienen el mismo family_id, por eso quien llama pide UNA por familia y
    reparte el resultado.
    """
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/reviews/item/{item_id}", headers=headers, params={"limit": 1}, timeout=10)
        if resp.status_code != 200:
            return None
        d = resp.json()
        niveles = {str(i + 1): int((d.get("rating_levels") or {}).get(clave) or 0)
                   for i, clave in enumerate(("one_star", "two_star", "three_star", "four_star", "five_star"))}
        total = int((d.get("paging") or {}).get("total") or 0)
        atributos = [{"texto": a.get("display_text"), "opciones": [{"nombre": o.get("name"), "porcentaje": o.get("percentage")} for o in a.get("histogram") or []]}
                     for a in d.get("quali_attributes") or [] if a.get("display_text")]
        criticas = []
        for estrellas in (1, 2, 3):
            if not niveles[str(estrellas)]:
                continue
            r = meli_http.get(f"https://api.mercadolibre.com/reviews/item/{item_id}", headers=headers, params={"limit": 3, "rating": estrellas}, timeout=10)
            if r.status_code == 200:
                criticas += [_opinion_critica(x) for x in (r.json().get("reviews") or [])]
        criticas.sort(key=lambda x: x["fecha"], reverse=True)
        return {"promedio": d.get("rating_average"), "total": total, "niveles": niveles, "atributos": atributos, "criticas": criticas[:6]}
    except Exception as e:
        print(f"[Enriquecimiento] ⚠️ Opiniones de {item_id}: {e}")
        return None


def refrescar_opiniones(usuario_id, cuenta_id, access_token, tope=TOPE["opiniones"]):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        pendientes = _pendientes(conexion.cursor(), cuenta_id, "opiniones_en", HORAS["opiniones"], "", tope, "id_meli, family_id")
    if not pendientes:
        return 0
    headers = {"Authorization": f"Bearer {access_token}"}
    # Una consulta por familia de publicaciones (family_id); sin ese dato, por publicación
    representantes = {}
    for id_meli, family_id in pendientes:
        representantes.setdefault(family_id or id_meli, (id_meli, family_id))
    resultados = _en_paralelo(lambda rep: (rep, datos_de_opiniones(rep[0], headers)), list(representantes.values()))
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for (id_meli, family_id), datos in resultados:
            if datos is None:
                continue
            valores = (datos["promedio"], datos["total"], json.dumps(datos["niveles"]), json.dumps(datos["atributos"]), json.dumps(datos["criticas"]))
            # El mismo resultado para todas las publicaciones de la familia
            cursor.execute("""
                UPDATE productos_padre SET opiniones_promedio = %s, opiniones_total = %s, opiniones_niveles = %s::jsonb,
                       opiniones_atributos = %s::jsonb, opiniones_criticas = %s::jsonb, opiniones_en = now()
                WHERE cuenta_id = %s AND (id_meli = %s OR (%s::text IS NOT NULL AND family_id = %s))
            """, valores + (cuenta_id, id_meli, family_id, family_id))
    return len(representantes)


def refrescar_todo(usuario_id, cuenta_id, access_token, capacidades=None):
    """Una pasada de cada uno (solo lo que aplica a la cuenta). Nunca levanta una excepción: es un extra, no puede frenar el sync."""
    caps = capacidades or {}
    pasos = [("calidad", refrescar_calidad), ("visitas", refrescar_visitas), ("opiniones", refrescar_opiniones)]
    if caps.get("full") is not False:
        pasos.append(("full", refrescar_full))
    if caps.get("catalogo") is not False:
        pasos.append(("catalogo", refrescar_catalogo))
    hechos = {}
    for nombre, funcion in pasos:
        try:
            hechos[nombre] = funcion(usuario_id, cuenta_id, access_token)
        except Exception as e:
            print(f"[Enriquecimiento] ⚠️ Cuenta {cuenta_id}, {nombre}: {e}")
    return hechos

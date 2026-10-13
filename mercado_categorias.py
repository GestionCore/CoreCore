"""
Categorías de Mercado Libre guardadas en la base (tabla global `mercado_categorias`, migración 0045): lo que se sabe de cada una y, sobre todo, QUÉ ATRIBUTOS DEFINEN UNA VARIANTE ahí.

Son datos públicos e iguales para todas las cuentas, así que se guardan una sola vez. Las escribe la conexión de administración (el rol de la app solo puede leer esas tablas);
las lee cualquiera. Lo usan dos módulos:
  · `mercado_relevador`: el trabajo diario que arma la historia del mercado.
  · el sincronizador de cada cuenta: la primera vez que ve una categoría pide sus atributos (dos llamadas) para saber qué distingue una variante de otra, en vez de adivinarlo del título.

Qué se verificó contra Mercado Libre real (docs/SONDEO_FASE0.md): `GET /categories/{id}/attributes` marca con `allow_variations` las dimensiones de variación (color, talle, acabado) y con
`hidden` los datos técnicos que el vendedor no ve (peso del paquete, GTIN, SKU). Memoria interna, RAM, litros, capacidad y voltaje NO llevan `allow_variations` pero tampoco `hidden`: son
atributos visibles que, cuando cambian entre las publicaciones de una misma familia, definen la variante (ver variantes.py).
"""
import meli_http

URL = "https://api.mercadolibre.com"
DIAS_VIGENCIA_ATRIBUTOS = 14          # una categoría casi no cambia sus atributos; se vuelven a pedir cada dos semanas
MAX_CATEGORIAS_NUEVAS_POR_SINCRONIZACION = 10


def _get(ruta, headers, params=None, timeout=12):
    """(estado, json|None). Nunca levanta: un tropiezo de red o un 403 puntual no tumba lo que viene después."""
    try:
        r = meli_http.get(URL + ruta, headers=headers or {}, params=params, timeout=timeout)
    except Exception as e:
        print(f"[Mercado] ⚠️ Error de conexión con {ruta}: {e}")
        return None, None
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except ValueError:
        return 200, None


# ── Lectura desde Mercado Libre (sin tocar la base) ──────────────────────────────────────────────────────────────────────────────────────
def leer_categoria(headers, category_id):
    """Los datos de una categoría tal como se guardan, o None si Mercado Libre no la devuelve."""
    estado, c = _get(f"/categories/{category_id}", headers)
    if estado != 200 or not isinstance(c, dict):
        return None
    camino = c.get("path_from_root") or []
    ajustes = c.get("settings") or {}
    return {
        "category_id": c.get("id") or category_id,
        "nombre": c.get("name") or category_id,
        "parent_id": camino[-2].get("id") if len(camino) >= 2 else None,
        "camino": [p.get("id") for p in camino] or [category_id],
        "camino_nombres": [p.get("name") for p in camino] or [c.get("name") or category_id],
        "dominio_id": ajustes.get("catalog_domain") or None,
        "es_hoja": not (c.get("children_categories") or []),
        "max_titulo": ajustes.get("max_title_length"),
        "max_variaciones": ajustes.get("max_variations_allowed"),
        "publicaciones": c.get("total_items_in_this_category"),
    }


def clasificar_atributos(atributos):
    """(variacion, ocultos): los ids que Mercado Libre marca `allow_variations` y los que marca `hidden` (datos técnicos que ninguna variante usa)."""
    variacion, ocultos = [], []
    for a in atributos or []:
        etiquetas = a.get("tags") or {}
        if not a.get("id"):
            continue
        if etiquetas.get("allow_variations"):
            variacion.append(a["id"])
        if etiquetas.get("hidden"):
            ocultos.append(a["id"])
    return variacion, sorted(set(ocultos))


def leer_atributos(headers, category_id):
    """(variacion, ocultos) de una categoría, o None si Mercado Libre no respondió (nunca se confunde «no sé» con «no tiene»)."""
    estado, lista = _get(f"/categories/{category_id}/attributes", headers)
    if estado != 200 or not isinstance(lista, list):
        return None
    return clasificar_atributos(lista)


# ── Base: escritura (conexión de administración) ─────────────────────────────────────────────────────────────────────────────────────────
def guardar_categoria(cursor, datos, seguir_desde=None):
    """
    Alta o actualización de una categoría y de sus ancestros (para tener el árbol hasta la raíz). `seguir_desde` (una fecha) la marca para el relevamiento diario.
    No toca los atributos de variación: esos los guarda `guardar_atributos`.
    """
    camino, nombres = datos["camino"], datos["camino_nombres"]
    for i, (cid, nombre) in enumerate(zip(camino[:-1], nombres[:-1])):
        cursor.execute(
            """INSERT INTO mercado_categorias (category_id, nombre, parent_id, camino, camino_nombres, es_hoja)
               VALUES (%s, %s, %s, %s, %s, false) ON CONFLICT (category_id) DO NOTHING""",
            (cid, nombre or cid, camino[i - 1] if i else None, camino[:i + 1], nombres[:i + 1]),
        )
    cursor.execute(
        """INSERT INTO mercado_categorias (category_id, nombre, parent_id, camino, camino_nombres, dominio_id, es_hoja, max_titulo, max_variaciones, publicaciones,
                                           seguida, ultimo_interes, actualizado_en)
           VALUES (%(category_id)s, %(nombre)s, %(parent_id)s, %(camino)s, %(camino_nombres)s, %(dominio_id)s, %(es_hoja)s, %(max_titulo)s, %(max_variaciones)s,
                   %(publicaciones)s, %(seguir)s, %(desde)s, now())
           ON CONFLICT (category_id) DO UPDATE SET
               nombre = EXCLUDED.nombre, parent_id = EXCLUDED.parent_id, camino = EXCLUDED.camino, camino_nombres = EXCLUDED.camino_nombres,
               dominio_id = EXCLUDED.dominio_id, es_hoja = EXCLUDED.es_hoja, max_titulo = EXCLUDED.max_titulo, max_variaciones = EXCLUDED.max_variaciones,
               publicaciones = EXCLUDED.publicaciones, actualizado_en = now(),
               seguida = mercado_categorias.seguida OR EXCLUDED.seguida,
               ultimo_interes = GREATEST(mercado_categorias.ultimo_interes, EXCLUDED.ultimo_interes)""",
        {**datos, "seguir": seguir_desde is not None, "desde": seguir_desde},
    )


def guardar_atributos(cursor, category_id, variacion, ocultos):
    cursor.execute(
        "UPDATE mercado_categorias SET atributos_variacion = %s, atributos_ocultos = %s, atributos_en = now() WHERE category_id = %s",
        (list(variacion), list(ocultos), category_id),
    )


# ── Base: lectura (la puede hacer cualquier cuenta) ──────────────────────────────────────────────────────────────────────────────────────
def dimensiones_de(cursor, category_ids):
    """
    {category_id: {"variacion": [...], "ocultos": [...], "al_dia": bool}} de las categorías que ya se conocen. `al_dia` es False si nunca se pidieron sus atributos o
    pasó la vigencia. Las que no están en la base no aparecen.
    """
    ids = sorted({c for c in category_ids if c})
    if not ids:
        return {}
    cursor.execute(
        """SELECT category_id, atributos_variacion, atributos_ocultos,
                  atributos_en IS NOT NULL AND atributos_en > now() - make_interval(days => %s)
           FROM mercado_categorias WHERE category_id = ANY(%s)""",
        (DIAS_VIGENCIA_ATRIBUTOS, ids),
    )
    return {fila[0]: {"variacion": list(fila[1] or []), "ocultos": list(fila[2] or []), "al_dia": bool(fila[3])} for fila in cursor.fetchall()}


def asegurar_dimensiones(cursor, category_ids, headers):
    """
    Las dimensiones de variación de cada categoría, completando las que falten con Mercado Libre (dos llamadas y una escritura por categoría nueva; como mucho
    MAX_CATEGORIAS_NUEVAS_POR_SINCRONIZACION por vez). `cursor` es el de la cuenta, que solo lee; la escritura de datos públicos va por la conexión de administración.
    Si Mercado Libre no responde devuelve lo que haya (puede ser nada): quien llama tiene que poder trabajar sin dimensiones.
    """
    import db
    conocidas = dimensiones_de(cursor, category_ids)
    faltan = [c for c in sorted({c for c in category_ids if c}) if not conocidas.get(c, {}).get("al_dia")][:MAX_CATEGORIAS_NUEVAS_POR_SINCRONIZACION]
    for category_id in faltan:
        atributos = leer_atributos(headers, category_id)
        if atributos is None:
            continue
        datos = leer_categoria(headers, category_id) if category_id not in conocidas else None
        try:
            with db.conexion_admin() as conexion:
                cur = conexion.cursor()
                if datos:
                    guardar_categoria(cur, datos)
                guardar_atributos(cur, category_id, *atributos)
            conocidas[category_id] = {"variacion": atributos[0], "ocultos": atributos[1], "al_dia": True}
        except Exception as e:
            print(f"[Mercado] ⚠️ No se pudieron guardar los atributos de {category_id}: {e}")
    return conocidas

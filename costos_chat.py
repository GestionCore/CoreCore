"""
Costos por chat — la IA convierte una descripción en lenguaje natural
("el alquiler me sale 150 mil por mes desde julio") en un gasto
estructurado, preguntando lo que falte (sobre todo el período) antes
de proponer guardar nada. Nunca escribe en la base directamente: solo
devuelve una PROPUESTA que el usuario tiene que confirmar a mano desde
el frontend, llamando a `confirmar_y_guardar` — así un malentendido de
la IA nunca termina como un gasto real sin que la persona lo revise.

También entiende costos de fabricación por producto ("todas las camperas
de jean valen $12000 y las medias $3000"). La IA solo extrae el grupo y el
monto; quién es "las camperas de jean" lo decide `resolver_grupos_de_productos`
(emparejamiento de palabras contra tus modelos, sin IA) y el usuario ve la
lista exacta de publicaciones antes de confirmar.
"""
import json
import re
import unicodedata
from datetime import datetime
import db
import ia_asistente
from utils import limpiar_titulo_modelo, hoy_argentina

PROMPT_SISTEMA = """Sos un asistente que ayuda a cargar datos de costos de un negocio que vende en Mercado Libre: gastos operativos (alquiler, sueldos, insumos) y costos de fabricación de productos. Tu única tarea es extraer datos estructurados de lo que te describe el usuario, o preguntar lo que falte — nunca conversás de otra cosa.

Hoy es {fecha_hoy}.

El usuario puede describir UNO o VARIOS gastos en el mismo mensaje (ej:
"gasté 70000 en bolsas el lunes y pagué 30000 a un ayudante el martes" son
DOS gastos distintos) — extraé todos los que aparezcan, no le pidas que
los mande de a uno.

Por cada mensaje del usuario, respondé ÚNICAMENTE con un objeto JSON (nada de texto antes o después, ni bloques de código), con una de estas dos formas:

1) Si falta información para cargar alguno de los gastos descriptos (sobre todo si no dijo desde cuándo aplica, o si el monto es ambiguo) — preguntá por TODOS los datos que falten en un solo mensaje, no de a uno:
{{"accion": "preguntar", "pregunta": "una sola pregunta corta y concreta, cubriendo todo lo que falte"}}

2) Si ya tenés todo lo necesario:
{{"accion": "confirmar", "gastos": [{{"concepto": "texto corto describiendo el gasto", "monto": 150000.0, "categoria": "fijo" o "variable", "recurrente": true o false, "fecha_desde": "YYYY-MM-DD", "fecha_fin": null o "YYYY-MM-DD"}}], "costos_productos": [{{"grupo": "termos de acero", "costo": 12000.0}}]}}
("gastos" y "costos_productos" son SIEMPRE listas; una de las dos puede ir vacía, pero no las dos.)

COSTOS DE PRODUCTOS: cuando el usuario dice cuánto le cuesta fabricar o comprar sus productos ("los termos de acero valen 12000", "cada par de medias me sale 3000", "el costo de las mochilas es 9000"), cada producto o grupo de productos es un elemento de "costos_productos". "grupo" es cómo el usuario nombró a esos productos, tal cual lo dijo, sin inventar ni agregar palabras ("todas", "el resto de" y similares no van en el grupo), y "costo" es el costo de UNA unidad en pesos. En esta pantalla, cuando el usuario dice cuánto "valen", "salen", "cuestan" o "hay que ponerles" a sus productos, SIEMPRE se entiende que es el costo de fabricación o compra: no le preguntes si es costo o precio de venta, ni si es por unidad o por pack (salvo que él mismo mencione vender, un precio de venta, o dé una cantidad como "la docena"). Si dice "el resto de los termos" es el mismo grupo general ("termos"): el sistema se encarga de que los grupos más específicos se queden con lo suyo. Un mensaje puede mezclar gastos y costos de productos: cargá los dos.

Reglas:
- "recurrente": true cuando el usuario describe algo que se repite todos los meses (alquiler, sueldo, un abono) — en ese caso "monto" es el importe MENSUAL.
- "recurrente": false para un gasto de una sola vez (una compra puntual, una reparación).
- "categoria" "fijo" = no cambia según cuánto vendés (alquiler, sueldos, abonos). "variable" = depende del volumen de venta (insumos, comisiones extra, envíos por fuera de MeLi).
- Si el usuario no aclaró desde cuándo aplica un gasto recurrente, SIEMPRE preguntá — no asumas "desde hoy" en silencio.
- Si no aclaró si es fijo o variable, decidilo vos según el tipo de gasto descrito, no preguntes por eso específicamente.
- "fecha_desde" para un gasto NO recurrente es la fecha en que se hizo/se hace ese gasto.
- Nunca inventes un monto ni una fecha que el usuario no haya dado o confirmado."""


def _limpiar_y_parsear_json(texto):
    texto = texto.strip()
    texto = re.sub(r'^```(?:json)?\s*|\s*```$', '', texto, flags=re.MULTILINE).strip()
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r'\{.*\}', texto, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# Palabras que no ayudan a identificar un producto ("todas las camperas de jean valen…")
_PALABRAS_VACIAS = {
    "de", "del", "la", "las", "el", "los", "lo", "y", "e", "con", "para", "un", "una", "unos", "unas",
    "todo", "todos", "toda", "todas", "mis", "mi", "sus", "su", "que", "en", "por", "al", "me",
    "sale", "salen", "vale", "valen", "cuesta", "cuestan", "costo", "costos",
    "resto", "demas", "otro", "otra", "otros", "otras", "tambien",
}
COSTO_MAXIMO = 1e12
MAX_PUBLICACIONES_POR_CARGA = 1000


def _singular(palabra):
    """Singular aproximado: "camperas" → "campera", "pantalones" → "pantalon", "jeans" → "jean". Se aplica igual a los títulos."""
    if len(palabra) > 4 and re.search(r'(ones|ores|ares|eles|ales|ices|ines)$', palabra):
        return palabra[:-2]
    if len(palabra) > 3 and palabra.endswith("s") and not palabra.endswith("ss"):
        return palabra[:-1]
    return palabra


def _palabras(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [_singular(p) for p in re.findall(r"[a-z0-9]+", t) if p not in _PALABRAS_VACIAS]


def _costo_valido(valor):
    try:
        costo = float(valor)
    except (TypeError, ValueError):
        return None
    return costo if 0 < costo < COSTO_MAXIMO else None


def resolver_grupos_de_productos(cursor, costos_productos):
    """
    Empareja cada grupo que dijo el usuario ("camperas de jean") con sus publicaciones reales: una publicación
    entra si su título tiene TODAS las palabras del grupo. Sin IA — es determinístico y el resultado se le muestra
    al usuario completo antes de tocar nada. Si una publicación entra en dos grupos ("camperas" y "camperas de
    jean") se la queda el más específico (el de más palabras).
    Devuelve una lista con un item por grupo: {grupo, costo, total, modelos: [{modelo, cantidad, ids, costo_actual_min, costo_actual_max}]}.
    """
    cursor.execute("SELECT id_meli, titulo, precio_costo FROM productos_padre")
    publicaciones = [(r[0], r[1], float(r[2] or 0.0), set(_palabras(r[1]))) for r in cursor.fetchall()]

    grupos = [{"grupo": cp["grupo"], "costo": cp["costo"], "palabras": set(_palabras(cp["grupo"]))} for cp in costos_productos]
    asignadas = {}   # id_meli → índice del grupo dueño
    for id_meli, _titulo, _costo, palabras_titulo in publicaciones:
        mejor = None
        for idx, gr in enumerate(grupos):
            if gr["palabras"] and gr["palabras"] <= palabras_titulo and (mejor is None or len(gr["palabras"]) > len(grupos[mejor]["palabras"])):
                mejor = idx
        if mejor is not None:
            asignadas[id_meli] = mejor

    salida = []
    for idx, gr in enumerate(grupos):
        por_modelo = {}
        for id_meli, titulo, costo_actual, _p in publicaciones:
            if asignadas.get(id_meli) != idx:
                continue
            modelo = limpiar_titulo_modelo(titulo) or titulo or "Sin nombre"
            m = por_modelo.setdefault(modelo, {"modelo": modelo, "ids": [], "costos": []})
            m["ids"].append(id_meli)
            m["costos"].append(costo_actual)
        modelos = [{"modelo": m["modelo"], "cantidad": len(m["ids"]), "ids": m["ids"],
                    "costo_actual_min": min(m["costos"]), "costo_actual_max": max(m["costos"])}
                   for m in sorted(por_modelo.values(), key=lambda m: m["modelo"])]
        salida.append({"grupo": gr["grupo"], "costo": gr["costo"], "total": sum(m["cantidad"] for m in modelos), "modelos": modelos})
    return salida


def _nombres_de_modelos(cursor, limite=8):
    cursor.execute("SELECT titulo FROM productos_padre ORDER BY titulo")
    modelos = []
    for (titulo,) in cursor.fetchall():
        m = limpiar_titulo_modelo(titulo) or titulo
        m = (m[:45].rsplit(' ', 1)[0] + '…') if m and len(m) > 45 else m
        if m and m not in modelos:
            modelos.append(m)
    return modelos[:limite]


def _pregunta_falta_dato():
    return {"accion": "preguntar", "pregunta": "Me falta un dato más — ¿me confirmás el monto y desde cuándo aplica cada gasto?"}


def procesar_mensaje(historial_mensajes, usuario_id=None, cuenta_id=None):
    """
    historial_mensajes: lista de {"role": "user"|"assistant", "content": "..."}
    con el historial completo de ESTA conversación de carga (se reinicia
    cada vez que se confirma o se cierra el chat).
    `usuario_id`/`cuenta_id` hacen falta para emparejar costos de productos con el catálogo de la cuenta.
    """
    prompt = PROMPT_SISTEMA.format(fecha_hoy=hoy_argentina().strftime("%Y-%m-%d"))
    # max_tokens generoso — un mensaje con varios gastos en una sola
    # confirmación necesita lugar para la lista JSON completa. 900 ya
    # había sido subido una vez para tolerar 2 gastos, pero seguía
    # cortando la respuesta a mitad de camino (JSON inválido → "no
    # terminé de entender eso") apenas el usuario describía un tercero.
    # 2000 deja margen cómodo para bastantes más sin acercarse al límite
    # real del modelo.
    ok, respuesta = ia_asistente.preguntar_ia_conversacion(prompt, historial_mensajes, max_tokens=2000, temperatura=0.2)

    if not ok:
        return {"accion": "error", "mensaje": f"No pude conectar con la IA ({respuesta}). Podés cargar el gasto a mano en el formulario de abajo."}

    parseado = _limpiar_y_parsear_json(respuesta)
    if not parseado or "accion" not in parseado:
        return {"accion": "preguntar", "pregunta": "No terminé de entender eso — ¿me lo describís de otra forma? Por ejemplo: \"el alquiler sale 150 mil por mes desde julio\"."}

    if parseado["accion"] != "confirmar":
        return parseado

    gastos = parseado.get("gastos") or []
    costos_productos = parseado.get("costos_productos") or []
    # Compatibilidad hacia atrás: si el modelo todavía devuelve el
    # gasto suelto en los campos de nivel superior (formato viejo,
    # de un solo ítem) en vez de la lista "gastos", lo envolvemos.
    if not gastos and not costos_productos and all(c in parseado for c in ("concepto", "monto", "categoria", "recurrente", "fecha_desde")):
        gastos = [parseado]
    if not isinstance(gastos, list) or not isinstance(costos_productos, list) or not (gastos or costos_productos):
        return _pregunta_falta_dato()

    campos_requeridos = ("concepto", "monto", "categoria", "recurrente", "fecha_desde")
    for g in gastos:
        if not isinstance(g, dict) or any(c not in g or g[c] is None for c in campos_requeridos):
            return _pregunta_falta_dato()

    limpios = []
    for cp in costos_productos:
        grupo = (cp.get("grupo") or "").strip() if isinstance(cp, dict) else ""
        costo = _costo_valido(cp.get("costo")) if isinstance(cp, dict) else None
        if not grupo or costo is None or not _palabras(grupo):
            return {"accion": "preguntar", "pregunta": "Me falta un dato más — ¿de qué productos hablás y cuánto cuesta cada unidad?"}
        limpios.append({"grupo": grupo, "costo": costo})

    if not limpios:
        return {"accion": "confirmar", "gastos": gastos, "costos_productos": []}

    if usuario_id is None or cuenta_id is None:
        return {"accion": "error", "mensaje": "No pude identificar tu cuenta para buscar esos productos."}
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        resueltos = resolver_grupos_de_productos(cursor, limpios)
        if not gastos and not any(r["total"] for r in resueltos):
            nombres = _nombres_de_modelos(cursor)
            no_encontrados = ", ".join(f"«{r['grupo']}»" for r in resueltos)
            ejemplos = ("Tus modelos son, por ejemplo: " + "; ".join(nombres) + ". ") if nombres else ""
            return {"accion": "preguntar", "pregunta": f"No encontré ninguna publicación que coincida con {no_encontrados}. {ejemplos}¿Cómo las nombrás?"}
    return {"accion": "confirmar", "gastos": gastos, "costos_productos": resueltos}


def confirmar_y_guardar(usuario_id, cuenta_id, propuestas, costos_productos=None):
    """
    `propuestas` es una lista (uno o más gastos confirmados juntos desde el
    mismo mensaje) y `costos_productos` una lista de {costo, ids} con las
    publicaciones EXACTAS que el usuario vio en pantalla. Se valida todo
    ANTES de escribir nada — si una sola cosa viene mal formada, no se
    guarda ninguna, para no dejar datos a medio cargar sin que el usuario
    lo pueda ver venir. Los ids que no sean de esta cuenta no se tocan:
    la política de RLS de productos_padre los deja fuera del UPDATE.
    Devuelve (True, {"gastos": n, "publicaciones": n}) o (False, mensaje_de_error).
    """
    propuestas = propuestas or []
    costos_productos = costos_productos or []
    if not isinstance(propuestas, list) or not isinstance(costos_productos, list) or not (propuestas or costos_productos):
        return False, "Faltan datos en la propuesta."

    campos_requeridos = ("concepto", "monto", "categoria", "recurrente", "fecha_desde")
    filas = []
    for propuesta in propuestas:
        if not isinstance(propuesta, dict) or any(c not in propuesta for c in campos_requeridos):
            return False, "Faltan datos en la propuesta."
        if propuesta["categoria"] not in ("fijo", "variable"):
            return False, "Categoría inválida."
        try:
            monto = float(propuesta["monto"])
            datetime.strptime(propuesta["fecha_desde"], "%Y-%m-%d")
            if propuesta.get("fecha_fin"):
                datetime.strptime(propuesta["fecha_fin"], "%Y-%m-%d")
        except (ValueError, TypeError):
            return False, "Monto o fecha con formato inválido."
        filas.append((cuenta_id, propuesta["concepto"], propuesta["categoria"], monto,
                       propuesta["fecha_desde"], bool(propuesta["recurrente"]), propuesta.get("fecha_fin")))

    cargas_costo = []
    total_ids = 0
    for cp in costos_productos:
        costo = _costo_valido(cp.get("costo")) if isinstance(cp, dict) else None
        ids = cp.get("ids") if isinstance(cp, dict) else None
        if costo is None or not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
            return False, "Costo de producto inválido."
        total_ids += len(ids)
        cargas_costo.append((costo, ids))
    if total_ids > MAX_PUBLICACIONES_POR_CARGA:
        return False, "Son demasiadas publicaciones de una vez — cargalas en partes."

    actualizadas = 0
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for fila in filas:
            cursor.execute("""
                INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha, recurrente, fecha_fin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, fila)
        for costo, ids in cargas_costo:
            cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE id_meli = ANY(%s)", (costo, ids))
            actualizadas += cursor.rowcount
    return True, {"gastos": len(filas), "publicaciones": actualizadas}

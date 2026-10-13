"""Costos — portado de Santi Mens. Lógica de negocio idéntica; cambia
el origen del cursor (RLS) y los placeholders (%s en vez de ?).

Los gastos RECURRENTES (alquiler, sueldos, abonos) se prorratean por
día dentro del período que se esté mirando — si elegís 14 días de un
mes de 30, un gasto recurrente de $150.000/mes cuenta como $150.000 * 14/30,
no el mes entero ni $0; un mes completo cuenta EXACTAMENTE el monto (cada día
vale el monto ÷ los días de su mes: ver utils.prorratear_mensual). Se prorratea
a propósito en vez de contar el mes completo siempre, para que el número tenga
sentido en períodos cortos como "últimos 7 días"."""
import re
from datetime import datetime
from psycopg.rows import dict_row
import db
from utils import formatear_moneda, limpiar_titulo_modelo, extraer_talle, prorratear_mensual


UMBRAL_AVISO_SIN_COSTO = 5       # % de lo facturado sin costo de fabricación a partir del cual se avisa que la ganancia puede estar inflada


def cobertura_de_costos(cursor, desde, hasta):
    """
    Qué parte de lo facturado en el período corresponde a publicaciones SIN costo de fabricación cargado. Es lo que infla la ganancia: cada venta de una
    publicación sin costo cuenta como si fabricarla fuera gratis. Se mide por plata (no por cantidad de publicaciones): una publicación que casi no
    vende y no tiene costo importa poco; la que más factura sin costo, mucho.
    Devuelve {"facturado", "sin_costo", "pct_sin_costo", "publicaciones", "avisar"}.
    """
    cursor.execute("""
        SELECT COALESCE(SUM(v.precio_venta * v.cantidad), 0),
               COALESCE(SUM(v.precio_venta * v.cantidad) FILTER (WHERE COALESCE(p.precio_costo, 0) <= 0), 0),
               COUNT(DISTINCT v.id_meli) FILTER (WHERE COALESCE(p.precio_costo, 0) <= 0)
        FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
        WHERE v.fecha_venta BETWEEN %s AND %s
    """, (desde, hasta))
    facturado, sin_costo, publicaciones = cursor.fetchone()
    facturado, sin_costo = float(facturado or 0), float(sin_costo or 0)
    pct = round(sin_costo / facturado * 100, 1) if facturado > 0 else 0.0
    return {"facturado": facturado, "sin_costo": sin_costo, "pct_sin_costo": pct, "publicaciones": int(publicaciones or 0),
            "avisar": facturado > 0 and pct >= UMBRAL_AVISO_SIN_COSTO}


def _talle_de_titulo(titulo):
    return extraer_talle(titulo)


def _palabras(texto):
    return (texto or "").split()


# Lo que parece un talle y no un color u otra versión: 2, 38, 35-41, S, M, L, XL, XXL, 3XL…
_PARECE_TALLE = re.compile(r"^(?:\d{1,2}(?:[-/]\d{1,2})?|x{0,3}[sl]|m|[2-5]xl)$", re.I)


def nombres_de_variantes(claves):
    """
    Dado el título-de-modelo de cada variante de UN mismo modelo (los colores u otras versiones: «Buzo Manta Beige Liso», «Buzo Manta Gris Liso»),
    devuelve (nombre común del modelo, {clave: etiqueta de la variante}). El nombre común son las palabras que comparten TODAS, en su orden; la etiqueta
    de cada una, las que la distinguen («Beige», «Gris»). Si no se distinguen por palabras (mismo texto en otro orden) la etiqueta es el título entero:
    nunca se inventa un nombre. Con una sola variante no hay nada que distinguir: sin etiqueta y el nombre es su título.
    """
    claves = list(dict.fromkeys(claves))
    if len(claves) <= 1:
        return (claves[0] if claves else ""), {c: "" for c in claves}
    conjuntos = [{p.lower() for p in _palabras(c)} for c in claves]
    comunes = set.intersection(*conjuntos)
    nombre = " ".join(p for p in _palabras(claves[0]) if p.lower() in comunes) or claves[0]
    etiquetas = {}
    for clave in claves:
        propias = " ".join(p for p in _palabras(clave) if p.lower() not in comunes)
        etiquetas[clave] = propias or clave
    return nombre, etiquetas


def _resumen_de_costos(items):
    """Cuántas activas sin costo, el rango de costos cargados y si hay que mirarlo (a medias o con alguna que pierde plata)."""
    activas = [i for i in items if i["estado"] == "active"]
    sin_costo = [i for i in activas if not i["precio_costo"]]
    cargados = [i["precio_costo"] for i in items if i["precio_costo"]]
    de_referencia = [i["precio_costo"] for i in (activas or items)]            # las pausadas no cuentan para saber si «todas valen lo mismo»
    return {
        "activo": bool(activas), "n_activas": len(activas), "sin_costo": len(sin_costo),
        "costo_min": min(cargados) if cargados else None, "costo_max": max(cargados) if cargados else None,
        "costo_comun": de_referencia[0] if de_referencia and de_referencia[0] and min(de_referencia) == max(de_referencia) else None,     # mismo costo en todas: el campo del grupo lo muestra
        "a_atender": bool((sin_costo and cargados) or any(i["ganancia_negativa"] for i in items)),
        "thumbnail": next((i["thumbnail"] for i in items if i["thumbnail"]), None),
    }


def agrupar_modelos(productos):
    """
    Las publicaciones de la pantalla Costos en tres niveles, sin suponer el rubro:
      · MODELO   = la familia de Mercado Libre (`family_id`: todos los colores y talles de un mismo producto); sin familia, el título sin su talle;
      · VARIANTE = cada título-de-modelo dentro de la familia (el color u otra versión): se carga UN costo para todas sus publicaciones;
      · PUBLICACIÓN = cada talle (o cada publicación de esa variante): el ajuste fino, que casi nunca hace falta.
    El costo se guarda siempre por publicación (`productos_padre.precio_costo`): esto solo decide cómo se ofrece cargarlo. Las que tienen costo que
    cargar van primero, después las activas y por último las pausadas.
    """
    familias = {}
    for p in productos:
        p = {**p, "rotulo": p["talle"]}                 # lo que dice la fila: el talle (o, si el talle está escrito en el título, lo que lo distingue)
        clave = ("familia", p["familia"]) if p.get("familia") else ("titulo", p["modelo"])
        familias.setdefault(clave, {}).setdefault(p["modelo"], []).append(p)
    modelos = []
    for variantes_por_clave in familias.values():
        nombre, etiquetas = nombres_de_variantes(list(variantes_por_clave))
        if len(variantes_por_clave) > 1 and all(_PARECE_TALLE.match(e) for e in etiquetas.values()):
            # Lo único que distingue a las «variantes» son talles escritos en medio del título («… Azul 2 Denim», «… Azul 3 Denim»): es UNA variante con varios talles
            items = []
            for clave, its in variantes_por_clave.items():
                for p in its:
                    if p["talle"] in (None, "", "Único"):
                        p["rotulo"] = etiquetas[clave]
                items.extend(its)
            variantes_por_clave, etiquetas = {nombre: items}, {nombre: ""}
        variantes = []
        for clave, items in variantes_por_clave.items():
            variantes.append({"clave": clave, "etiqueta": etiquetas[clave], "filas": items, **_resumen_de_costos(items)})
        variantes.sort(key=lambda v: (not v["activo"], -v["sin_costo"], v["etiqueta"].lower()))
        todos = [i for v in variantes for i in v["filas"]]
        modelos.append({"nombre": nombre, "variantes": variantes, "filas": todos, "n_variantes": len(variantes), "n_publicaciones": len(todos), **_resumen_de_costos(todos)})
    modelos.sort(key=lambda m: (not m["activo"], -m["sin_costo"], m["nombre"].lower()))
    return modelos


def obtener_datos_costos(usuario_id, fecha_desde, fecha_hasta, cuenta_id=None):
    fecha_desde_dt = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
    fecha_hasta_dt = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT id, concepto, categoria, monto, fecha, recurrente, fecha_fin FROM gastos_operativos
            WHERE (recurrente = false AND fecha BETWEEN %s AND %s)
               OR (recurrente = true AND fecha <= %s AND (fecha_fin IS NULL OR fecha_fin >= %s))
            ORDER BY fecha DESC, id DESC
        """, (fecha_desde, fecha_hasta, fecha_hasta, fecha_desde))
        gastos_db = cursor.fetchall()

        gastos = []
        total_fijos = 0.0
        total_variables = 0.0
        for fila in gastos_db:
            monto_base = float(fila["monto"])
            if fila["recurrente"]:
                monto = prorratear_mensual(monto_base, fila["fecha"], fila["fecha_fin"], fecha_desde_dt, fecha_hasta_dt)
            else:
                monto = monto_base

            if fila["categoria"] == "fijo": total_fijos += monto
            else: total_variables += monto

            fecha_fmt = fila["fecha"].strftime("%Y-%m-%d") if hasattr(fila["fecha"], "strftime") else fila["fecha"]
            gastos.append({
                "id": fila["id"], "concepto": fila["concepto"], "categoria": fila["categoria"],
                "monto_formateado": formatear_moneda(monto), "fecha": fecha_fmt,
                "recurrente": fila["recurrente"],
                "monto_mensual_formateado": formatear_moneda(monto_base) if fila["recurrente"] else None,
            })

        cursor.execute("""
            SELECT p.id_meli, p.titulo, p.precio_costo, p.estado, p.thumbnail, p.precio, p.recibis_estimado, p.family_id
            FROM productos_padre p
            ORDER BY CASE WHEN p.estado = 'active' THEN 0 ELSE 1 END, p.titulo
        """)
        filas_costo = cursor.fetchall()

        # Esta consulta antes leía por posición (r[0], r[1]...) — con
        # dict_row el resultado es un diccionario, así que hace falta el
        # nombre real de columna. Le puse alias explícito a AVG() para no
        # depender del nombre que Postgres le pone por default a una
        # columna calculada sin alias.
        cursor.execute("SELECT id_meli, AVG(costo_envio) AS envio_promedio FROM ventas WHERE costo_envio > 0 GROUP BY id_meli")
        envio_promedio_por_item = {r["id_meli"]: float(r["envio_promedio"]) for r in cursor.fetchall()}

    productos_costo = []
    for fila in filas_costo:
        precio_costo_p = float(fila["precio_costo"] or 0.0)
        precio_p = float(fila["precio"] or 0.0)
        recibis_p = float(fila["recibis_estimado"]) if fila["recibis_estimado"] is not None else None
        comision_est = round(precio_p - recibis_p, 2) if recibis_p else None
        envio_prom = round(envio_promedio_por_item.get(fila["id_meli"], 0.0), 2)
        ganancia_neta = None
        segmentos_pct = None
        if comision_est is not None and precio_p > 0:
            ganancia_neta = round(precio_p - comision_est - envio_prom - precio_costo_p, 2)
            segmentos_pct = {
                "costo": round((precio_costo_p / precio_p) * 100, 1),
                "envio": round((envio_prom / precio_p) * 100, 1),
                "comision": round((comision_est / precio_p) * 100, 1),
                "ganancia": round(max(ganancia_neta, 0) / precio_p * 100, 1),
            }
        productos_costo.append({
            "id": fila["id_meli"], "titulo": fila["titulo"], "precio_costo": precio_costo_p,
            "precio_costo_formateado": formatear_moneda(precio_costo_p), "estado": fila["estado"],
            "thumbnail": fila["thumbnail"],
            "precio_formateado": formatear_moneda(precio_p) if precio_p else None,
            "comision_formateada": formatear_moneda(comision_est) if comision_est is not None else None,
            "envio_formateado": formatear_moneda(envio_prom) if envio_prom else None,
            "ganancia_neta_formateada": formatear_moneda(ganancia_neta) if ganancia_neta is not None else None,
            "ganancia_negativa": ganancia_neta is not None and ganancia_neta < 0,
            "segmentos_pct": segmentos_pct,
            # Crudos + agrupación por modelo: la pantalla recalcula la ganancia en vivo al tipear un costo
            # y deja cargar el mismo costo a todos los talles de un modelo de una vez.
            "precio": precio_p, "comision": comision_est, "envio": envio_prom,
            "modelo": limpiar_titulo_modelo(fila["titulo"]) or (fila["titulo"] or "Sin nombre"),
            "talle": _talle_de_titulo(fila["titulo"]),
            "familia": fila.get("family_id") or None,
        })

    stats_gastos = {
        "fijos": formatear_moneda(total_fijos), "variables": formatear_moneda(total_variables), "total": formatear_moneda(total_fijos + total_variables),
        # Crudos (no texto) — los usa el punto de equilibrio de Ganancia
        # Real, que necesita sumar/dividir de verdad, no solo mostrar.
        "fijos_raw": round(total_fijos, 2), "variables_raw": round(total_variables, 2),
    }
    return gastos, stats_gastos, productos_costo

"""
Costo de fabricación en pesos o en dólares, a nivel publicación o variante.

Cómo se guarda (migración 0050):
  · `precio_costo` es SIEMPRE el costo en PESOS: es lo que leen la Ganancia Real y casi todas las pantallas (no se tocó ninguna de esas consultas);
  · `costo_original` + `moneda_costo` ('ARS' o 'USD') dicen lo que la persona escribió. Con USD, `precio_costo = costo_original × la cotización activa de la cuenta`
    (dolar.cotizacion_activa: el MEP automático o su dólar manual), redondeado a centavos;
  · cuando esa cotización cambia —la persona cambia su dólar manual, o el scheduler trae un MEP nuevo y la cuenta usa el automático— `recalcular_cuenta` vuelve a
    convertir todos los costos en dólares: la Ganancia Real siempre usa el costo de reposición de hoy;
  · el costo de una VARIANTE (`productos_variantes`) manda sobre el de su publicación; una variante sin costo propio (NULL) usa el de la publicación.
TODA escritura de un costo pasa por `guardar_costo_publicacion` / `guardar_costo_variante`: una que escribiera solo `precio_costo` dejaría `moneda_costo = 'USD'` con un
costo viejo y el próximo recálculo pisaría lo que la persona acaba de cargar (hay una prueba que lo impide).
El código tolera que la migración 0050 todavía no esté aplicada: en pesos escribe como siempre; en dólares avisa que se activa con la próxima actualización.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import psycopg

from utils import sql_variante_de_venta

MONEDAS = ("ARS", "USD")
MONTO_MAXIMO = 1e12


def normalizar_monto(valor):
    """El monto como número con 2 decimales (0 o más), o None si no sirve (texto, vacío, negativo, NaN, infinito o absurdo)."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    if v != v or not 0 <= v < MONTO_MAXIMO:
        return None
    return round(v, 2)


def normalizar_moneda(valor):
    """'ARS' o 'USD' (sin importar mayúsculas); None si no se indicó ninguna; False si indicó algo que no es una moneda."""
    if valor in (None, ""):
        return None
    m = str(valor).strip().upper()
    return m if m in MONEDAS else False


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def a_pesos(monto, moneda, valor_dolar):
    """El costo en pesos: el mismo monto si es ARS; monto × dólar si es USD (None si falta la cotización: nunca se supone una)."""
    if moneda == "USD":
        dolar = _decimal(valor_dolar)
        if dolar is None or dolar <= 0:
            return None
        return float((Decimal(str(monto)) * dolar).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))      # en Decimal: el mismo redondeo que ROUND() de la base, sin diferencias de un centavo
    return round(monto, 2)


MENSAJE_SIN_DOLAR = "Para cargar un costo en dólares hace falta una cotización: elegí tu dólar en «Mi cuenta» (automático o manual) y volvé a intentar."
MENSAJE_SIN_MIGRACION = "Los costos en dólares se activan con la próxima actualización de CoreLux."


def guardar_costo_publicacion(cursor, cuenta_id, ids_meli, monto, moneda="ARS", valor_dolar=None):
    """
    Guarda el costo de una o varias publicaciones (`ids_meli`: un id o una lista). Devuelve (ok, mensaje, filas): `filas` = cuántas publicaciones actualizó. Un costo en dólares
    sin cotización o un monto inválido no cambia nada. Un cambio a pesos pisa un costo que estaba en dólares (la moneda queda bien).
    """
    ids = [ids_meli] if isinstance(ids_meli, str) else list(ids_meli)
    monto, moneda_ok = normalizar_monto(monto), normalizar_moneda(moneda)
    if monto is None:
        return False, "El costo tiene que ser un número de cero o más.", 0
    if moneda_ok is False:
        return False, "La moneda tiene que ser pesos o dólares.", 0
    moneda = moneda_ok or "ARS"
    pesos = a_pesos(monto, moneda, valor_dolar)
    if pesos is None:
        return False, MENSAJE_SIN_DOLAR, 0
    try:
        with cursor.connection.transaction():
            cursor.execute("UPDATE productos_padre SET precio_costo = %s, costo_original = %s, moneda_costo = %s WHERE cuenta_id = %s AND id_meli = ANY(%s)",
                           (pesos, monto, moneda, cuenta_id, ids))
            return True, "Costo guardado.", cursor.rowcount
    except psycopg.errors.UndefinedColumn:                           # migración 0050 pendiente
        if moneda == "USD":
            return False, MENSAJE_SIN_MIGRACION, 0
        cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE cuenta_id = %s AND id_meli = ANY(%s)", (pesos, cuenta_id, ids))
        return True, "Costo guardado.", cursor.rowcount


def guardar_costo_variante(cursor, cuenta_id, id_variante, monto, moneda="ARS", valor_dolar=None):
    """
    Guarda el costo de UNA variante de Mercado Libre (manda sobre el de su publicación). Un monto 0 quita el costo propio de la variante: vuelve a usar el de la publicación.
    Devuelve (ok, mensaje, filas).
    """
    monto, moneda_ok = normalizar_monto(monto), normalizar_moneda(moneda)
    if monto is None:
        return False, "El costo tiene que ser un número de cero o más.", 0
    if moneda_ok is False:
        return False, "La moneda tiene que ser pesos o dólares.", 0
    moneda = moneda_ok or "ARS"
    try:
        with cursor.connection.transaction():
            if monto == 0:
                cursor.execute("UPDATE productos_variantes SET precio_costo = NULL, costo_original = NULL, moneda_costo = NULL WHERE cuenta_id = %s AND id_variante = %s", (cuenta_id, id_variante))
                return True, "Esa variante vuelve a usar el costo de la publicación.", cursor.rowcount
            pesos = a_pesos(monto, moneda, valor_dolar)
            if pesos is None:
                return False, MENSAJE_SIN_DOLAR, 0
            cursor.execute("UPDATE productos_variantes SET precio_costo = %s, costo_original = %s, moneda_costo = %s WHERE cuenta_id = %s AND id_variante = %s",
                           (pesos, monto, moneda, cuenta_id, id_variante))
            return True, "Costo guardado.", cursor.rowcount
    except psycopg.errors.UndefinedColumn:
        if moneda == "USD" and monto != 0:
            return False, MENSAJE_SIN_MIGRACION, 0
        if monto == 0:
            cursor.execute("UPDATE productos_variantes SET precio_costo = NULL, moneda_costo = NULL WHERE cuenta_id = %s AND id_variante = %s", (cuenta_id, id_variante))
        else:
            cursor.execute("UPDATE productos_variantes SET precio_costo = %s WHERE cuenta_id = %s AND id_variante = %s", (a_pesos(monto, "ARS", None), cuenta_id, id_variante))
        return True, "Costo guardado.", cursor.rowcount


def recalcular_cuenta(cursor, cuenta_id, valor_dolar):
    """
    Vuelve a convertir a pesos todos los costos en dólares de la cuenta con la cotización `valor_dolar` (precio_costo = costo_original × dólar). Los costos en pesos no se tocan.
    Sin cotización no hace nada (nunca se pisa un costo con un número supuesto). Devuelve cuántas filas cambió; 0 si la migración 0050 todavía no está.
    """
    dolar = _decimal(valor_dolar)
    if dolar is None or not dolar > 0:
        return 0
    filas = 0
    try:
        with cursor.connection.transaction():
            for tabla in ("productos_padre", "productos_variantes"):
                cursor.execute(f"UPDATE {tabla} SET precio_costo = ROUND(costo_original * %s::numeric, 2) WHERE cuenta_id = %s AND moneda_costo = 'USD' AND costo_original IS NOT NULL "
                               f"AND precio_costo IS DISTINCT FROM ROUND(costo_original * %s::numeric, 2)", (dolar, cuenta_id, dolar))
                filas += cursor.rowcount
    except psycopg.errors.UndefinedColumn:
        return 0
    return filas


# ── El costo que usa cada VENTA: el de su variante si la persona cargó uno, y si no el de su publicación ───────────────────────────────────────────

def sql_costo_de_venta(v="v", p="p"):
    """
    (JOIN, expresión) de SQL para consultas que leen `ventas` (alias `v`) con su publicación (alias `p`, productos_padre): el costo en pesos de UNA unidad de esa venta. La variante
    de la venta es `ventas.id_variante`; una publicación sin variaciones se guarda como «<id>_unica». Una variante sin costo propio (NULL o 0) usa el de la publicación.
    """
    join = f"LEFT JOIN productos_variantes pv ON pv.cuenta_id = {v}.cuenta_id AND pv.id_variante = {sql_variante_de_venta(v)}"
    return join, f"COALESCE(NULLIF(pv.precio_costo, 0), NULLIF({p}.precio_costo, 0), 0)"


def variante_de_venta(id_meli, id_variante):
    """La clave de `productos_variantes` de una venta (misma regla que sql_costo_de_venta)."""
    return id_variante or f"{id_meli}_unica"


def costo_de_venta(id_meli, id_variante, costos_por_item, costos_por_variante):
    """El costo en pesos de una unidad de una venta, en Python: `costos_por_variante` = {id_variante: costo} solo de las variantes con costo propio."""
    propio = costos_por_variante.get(variante_de_venta(id_meli, id_variante))
    if propio:
        return float(propio)
    return float(costos_por_item.get(id_meli) or 0.0)


# ── Lo que se muestra: el costo original de cada publicación y variante ───────────────────────────────────────────────────────────────────────

def costos_originales(cursor, cuenta_id):
    """
    Para las pantallas de costos: ({id_meli: {"moneda": "USD", "original"}} de las publicaciones con costo cargado en DÓLARES,
    {id_meli: [{"id_variante", "etiqueta", "pesos", "moneda", "original"}]} de las publicaciones con MÁS DE UNA variante, con el costo propio de cada una).
    `pesos` es None si la variante no tiene costo propio (usa el de la publicación). Sin la migración 0050 no puede haber costos en dólares todavía: las publicaciones salen vacías
    y las variantes en pesos.
    """
    if cuenta_id is None:
        return {}, {}
    try:
        with cursor.connection.transaction():
            cursor.execute("SELECT id_meli, costo_original FROM productos_padre WHERE cuenta_id = %s AND moneda_costo = 'USD' AND costo_original IS NOT NULL", (cuenta_id,))
            publicaciones = {i: {"moneda": "USD", "original": float(o)} for i, o in cursor.fetchall()}
    except psycopg.errors.UndefinedColumn:
        publicaciones = {}
    consulta = ("SELECT p.id_meli, v.id_variante, v.etiqueta, NULLIF(v.precio_costo, 0), COALESCE(v.moneda_costo, 'ARS'), {original} "
                "FROM productos_variantes v JOIN productos_padre p ON p.id = v.id_padre "
                "WHERE v.cuenta_id = %s AND v.id_padre IN (SELECT id_padre FROM productos_variantes WHERE cuenta_id = %s GROUP BY id_padre HAVING COUNT(*) > 1) "
                "ORDER BY p.id_meli, v.etiqueta, v.id_variante")
    try:
        with cursor.connection.transaction():
            cursor.execute(consulta.format(original="v.costo_original"), (cuenta_id, cuenta_id))
            filas = cursor.fetchall()
    except psycopg.errors.UndefinedColumn:
        with cursor.connection.transaction():
            cursor.execute(consulta.format(original="NULL"), (cuenta_id, cuenta_id))
            filas = cursor.fetchall()
    variantes = {}
    for id_meli, id_variante, etiqueta, pesos, moneda, original in filas:
        variantes.setdefault(id_meli, []).append({
            "id_variante": id_variante, "etiqueta": etiqueta or "Única", "pesos": float(pesos) if pesos is not None else None, "moneda": moneda,
            "original": float(original) if original is not None else (float(pesos) if pesos is not None else None)})
    return publicaciones, variantes

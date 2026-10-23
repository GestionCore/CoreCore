"""
Avance de la PRIMERA sincronización (N10): cuánto se espera traer, para que la pantalla de espera diga «1.240 de ~3.000 órdenes» y no solo «1.240».

Cuando arranca la importación se anotan los totales que informa Mercado Libre (cuántas publicaciones tiene la cuenta y cuántas órdenes hay en el último año) en la caché compartida
(`cache_db`, por cuenta). `/api/estado_sincronizacion` los lee junto con lo que ya entró. Son estimaciones: una orden cancelada cuenta en el total de Mercado Libre pero nunca se guarda, así que
la cuenta puede llegar a «2.870 de ~3.000» y terminar igual; por eso siempre se muestran con «~». Anotar jamás frena ni rompe la sincronización.
"""
import cache_db
import db

CLAVE = "sync_totales"
FIRMA = "v1"
TTL_SEGUNDOS = 24 * 3600


def guardar(cursor, cuenta_id, **totales):
    """Suma `totales` (publicaciones=…, ventas=…) a lo que ya había anotado; ignora lo que no sea un entero positivo. Devuelve el diccionario resultante."""
    _, actual = cache_db.leer(cursor, cuenta_id, CLAVE, FIRMA, ttl_segundos=TTL_SEGUNDOS)
    anotados = dict(actual) if isinstance(actual, dict) else {}
    nuevos = {k: int(v) for k, v in totales.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
    if nuevos and any(anotados.get(k) != v for k, v in nuevos.items()):
        anotados.update(nuevos)
        cache_db.guardar(cursor, cuenta_id, CLAVE, anotados, FIRMA)
    return anotados


def anotar(usuario_id, cuenta_id, **totales):
    """Como `guardar`, abriendo su propia conexión. Nunca levanta una excepción: un total que no se pudo anotar solo significa que la pantalla muestra lo que ya entró, sin el «de ~N»."""
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            return guardar(conexion.cursor(), cuenta_id, **totales)
    except Exception as e:
        print(f"[SyncAvance] ⚠️ No se pudo anotar el total esperado de la cuenta {cuenta_id}: {e}")
        return {}


FRACCION_PARA_DAR_POR_TRAIDAS = 0.9


def faltan_ordenes(ordenes, esperadas, en_curso):
    """True si la importación sigue y todavía no entró casi todo lo esperado (el 90 %: las canceladas cuentan en el total de Mercado Libre pero nunca se guardan). Sin total conocido, False: se comporta como siempre."""
    return bool(en_curso and esperadas and ordenes < esperadas * FRACCION_PARA_DAR_POR_TRAIDAS)


def leer(cursor, cuenta_id):
    """{'publicaciones': N, 'ventas': M} con lo que se anotó (puede faltar alguna clave): el total esperado de lo que se está importando."""
    try:
        hit, valor = cache_db.leer(cursor, cuenta_id, CLAVE, FIRMA, ttl_segundos=TTL_SEGUNDOS)
    except Exception:
        return {}
    return {k: v for k, v in valor.items() if k in ("publicaciones", "ventas") and isinstance(v, int) and v > 0} if hit and isinstance(valor, dict) else {}

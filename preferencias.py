"""
Preferencias de cada cuenta. Hoy una sola: el margen mínimo aceptable, que antes estaba fijo en 15 % en seis lugares.

El código tolera que la columna (migración 0035) todavía no exista: usa el valor de siempre. Así el deploy puede aplicar la migración antes o después
sin que ninguna pantalla falle en el medio.
"""
import db

MARGEN_MINIMO_DEFECTO = 15.0
MARGEN_MINIMO_MAXIMO = 60.0


def normalizar_margen(valor):
    """El margen como número entre 0 y 60 con un decimal, o None si no es un número válido (texto, vacío, negativo, mayor a 60)."""
    try:
        numero = float(str(valor).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    if numero != numero or not (0 <= numero <= MARGEN_MINIMO_MAXIMO):      # numero != numero: NaN
        return None
    return round(numero, 1)


def margenes_de_usuario(usuario_id):
    """{cuenta_id: margen mínimo} de todas las cuentas del usuario. Sin la columna o sin base, todas en el valor por defecto."""
    try:
        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT id, margen_minimo FROM cuentas_meli WHERE usuario_id = %s", (usuario_id,))
            return {fila[0]: float(fila[1]) for fila in cursor.fetchall()}
    except Exception as e:
        print(f"[Preferencias] ℹ️ Se usa el margen mínimo por defecto ({MARGEN_MINIMO_DEFECTO} %): {e}")
        return {}


def guardar_margen_minimo(cursor, cuenta_id, valor):
    """Guarda el margen mínimo de la cuenta. Devuelve el valor guardado o None si no era válido."""
    margen = normalizar_margen(valor)
    if margen is None:
        return None
    cursor.execute("UPDATE cuentas_meli SET margen_minimo = %s WHERE id = %s", (margen, cuenta_id))
    return margen

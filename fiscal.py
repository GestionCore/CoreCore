"""
Condición fiscal de cada cuenta de Mercado Libre.

REGLA: nunca se supone. No todos los vendedores son monotributistas (hay responsables inscriptos y quien todavía no está inscripto), así que lo que
depende de la condición fiscal (hoy, la pantalla de Monotributo) solo se muestra a quien la declaró, y a quien no la contó se le pregunta.
Un `None` significa "no sabemos": no esconde nada del menú y no habilita ningún cálculo que la suponga.

Mercado Libre informa el CUIT/DNI del vendedor (`GET /users/me` → identification) pero NO su condición ante ARCA. Confirmarla sin preguntar requeriría consultar el
padrón de ARCA con un certificado propio de CoreLux (servicio de constancia de inscripción); mientras tanto la declara la persona (`condicion_fiscal_origen = 'declarada'`).
"""
import db

MONOTRIBUTO = "monotributo"
RESPONSABLE_INSCRIPTO = "responsable_inscripto"
SIN_INSCRIPCION = "sin_inscripcion"

CONDICIONES = {
    MONOTRIBUTO: "Monotributista",
    RESPONSABLE_INSCRIPTO: "Responsable inscripto",
    SIN_INSCRIPCION: "Todavía no estoy inscripto en ARCA",
}
DETALLES = {
    MONOTRIBUTO: "Pagás una cuota mensual según tu categoría.",
    RESPONSABLE_INSCRIPTO: "Facturás con IVA y presentás declaraciones.",
    SIN_INSCRIPCION: "Vendés sin estar inscripto: conviene regularizarlo con un contador.",
}


def es_valida(condicion):
    return condicion in CONDICIONES


def etiqueta(condicion):
    return CONDICIONES.get(condicion) or "Sin informar"


def capacidad_monotributo(condicion):
    """
    Para `capacidades` (lo que esconde una pantalla): True si es monotributista, False si SE SABE que no lo es, None si no sabemos. Solo un False esconde la pantalla de Monotributo.
    """
    if condicion is None or not es_valida(condicion):
        return None
    return condicion == MONOTRIBUTO


def obtener(usuario_id, cuenta_id):
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT condicion_fiscal FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        fila = cursor.fetchone()
    return fila[0] if fila and es_valida(fila[0]) else None


def guardar(usuario_id, cuenta_id, condicion):
    """Guarda lo que declaró la persona. `None` o vacío = "todavía no lo sé": vuelve a quedar sin informar. Devuelve False si el valor no existe."""
    condicion = condicion or None
    if condicion is not None and not es_valida(condicion):
        return False
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE cuentas_meli SET condicion_fiscal = %s, condicion_fiscal_origen = %s, condicion_fiscal_en = now() WHERE id = %s",
            (condicion, "declarada" if condicion else None, cuenta_id),
        )
    return True

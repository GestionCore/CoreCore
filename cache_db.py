"""
Caché compartida por cuenta, guardada en la base (tabla cache_valores).

A diferencia de un diccionario a nivel de módulo (uno por proceso, y un riesgo conocido de mezclar cuentas), esta caché la ven todos los
procesos y siempre va atada a una cuenta_id con RLS. Es para valores caros de calcular o de pedir y que se pueden servir un rato "viejos".

    hit, valor = cache_db.leer(cursor, cuenta_id, "coach_ia", firma, ttl_segundos=6 * 3600, ttl_fallido=600)
    if not hit:
        valor = calcular()                       # puede ser None si falló: se recuerda un rato (ttl_fallido) para no reintentar en cada carga
        cache_db.guardar(cursor, cuenta_id, "coach_ia", valor, firma)

`firma` identifica de qué depende el valor: si cambia, lo guardado ya no vale. Lo que se guarda tiene que poder serializarse a JSON.
"""
import json


def leer(cursor, cuenta_id, clave, firma="", ttl_segundos=3600, ttl_fallido=None):
    """
    (hit, valor). hit es False si no hay nada vigente (no existe, la firma cambió o venció). Un valor None con hit True es un intento fallido
    recordado: no vuelve a intentarse hasta que pase ttl_fallido (por defecto, lo mismo que ttl_segundos).
    """
    cursor.execute(
        "SELECT valor, firma, EXTRACT(EPOCH FROM (clock_timestamp() - actualizado_en)) FROM cache_valores WHERE cuenta_id = %s AND clave = %s",
        (cuenta_id, clave),
    )
    fila = cursor.fetchone()
    if not fila:
        return False, None
    valor, firma_guardada, edad = fila
    contenido = (valor or {}).get("v")
    limite = ttl_segundos if contenido is not None else (ttl_fallido if ttl_fallido is not None else ttl_segundos)
    if firma_guardada != firma or edad is None or float(edad) > limite:
        return False, None
    return True, contenido


def guardar(cursor, cuenta_id, clave, valor, firma=""):
    cursor.execute(
        """
        INSERT INTO cache_valores (cuenta_id, clave, firma, valor, actualizado_en) VALUES (%s, %s, %s, %s::jsonb, now())
        ON CONFLICT (cuenta_id, clave) DO UPDATE SET firma = excluded.firma, valor = excluded.valor, actualizado_en = now()
        """,
        (cuenta_id, clave, firma, json.dumps({"v": valor})),
    )


def borrar(cursor, cuenta_id, clave):
    cursor.execute("DELETE FROM cache_valores WHERE cuenta_id = %s AND clave = %s", (cuenta_id, clave))

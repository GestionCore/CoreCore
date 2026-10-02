"""
"Descargar mis datos": un zip con una carpeta por cuenta de Mercado Libre del usuario y un CSV por tabla (ventas, publicaciones, costos, gastos, reclamos…).

Se lee con la conexión DEL USUARIO (db.conexion_usuario), no con la de administración: la seguridad por cuenta (RLS) es la que decide qué sale, así que ni un
error en este módulo puede mezclar datos de otra persona. Los tokens de acceso a Mercado Libre no se incluyen: no son datos de la persona y no se pueden leer con ese rol.
"""
import datetime
import io
import re
import zipfile

import db
from utils import ARGENTINA

TABLAS_EXCLUIDAS = {"meli_tokens", "cache_valores", "schema_migrations"}


def nombre_de_carpeta(cuenta, usadas):
    """Un nombre de carpeta seguro y único para una cuenta ("DIEGO", "Mi tienda_7")."""
    base = re.sub(r"[^\w.-]+", "_", str(cuenta.get("nombre_negocio") or cuenta.get("nickname") or f"cuenta_{cuenta['id']}")).strip("._ ") or f"cuenta_{cuenta['id']}"          # sin puntos al borde: un apodo ".." sería una carpeta ".." (zip slip al descomprimir)
    nombre = base if base not in usadas else f"{base}_{cuenta['id']}"
    usadas.add(nombre)
    return nombre


def tablas_con_cuenta(cursor):
    cursor.execute("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'cuenta_id' ORDER BY table_name")
    return [fila[0] for fila in cursor.fetchall() if fila[0] not in TABLAS_EXCLUIDAS]


def _csv_de_tabla(cursor, tabla):
    """El CSV de una tabla tal como la ve el usuario (RLS). None si no se puede leer; un fallo no echa a perder el resto (savepoint)."""
    cursor.execute("SAVEPOINT leer_tabla")
    try:
        salida = io.StringIO()
        with cursor.copy(f'COPY (SELECT * FROM "{tabla}") TO STDOUT WITH (FORMAT csv, HEADER true)') as copia:
            for bloque in copia:
                salida.write(bytes(bloque).decode("utf-8"))
        cursor.execute("RELEASE SAVEPOINT leer_tabla")
        return salida.getvalue()
    except Exception as e:
        print(f"[MisDatos] ⚠️ No se pudo leer {tabla}: {e}")
        cursor.execute("ROLLBACK TO SAVEPOINT leer_tabla")
        return None


def armar_zip(usuario_id, cuentas):
    """(bytes del zip, resumen [(carpeta, tabla, filas)]). `cuentas` es la lista de cuentas del usuario (dicts con id, nickname, nombre_negocio)."""
    memoria = io.BytesIO()
    resumen, usadas = [], set()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as zf:
        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT id, email, nombre, plan, creado_en FROM usuarios WHERE id = %s", (usuario_id,))
            fila = cursor.fetchone()
            if fila:
                zf.writestr("usuario.csv", "id,email,nombre,plan,creado_en\n" + ",".join('"' + str(v if v is not None else "").replace('"', '""') + '"' for v in fila) + "\n")
        for cuenta in cuentas:
            carpeta = nombre_de_carpeta(cuenta, usadas)
            with db.conexion_usuario(usuario_id, cuenta["id"]) as conexion:
                cursor = conexion.cursor()
                for tabla in tablas_con_cuenta(cursor):
                    contenido = _csv_de_tabla(cursor, tabla)
                    if contenido is None:
                        continue
                    filas = max(contenido.count("\n") - 1, 0)
                    if filas == 0:
                        continue                                  # una tabla vacía no aporta un archivo
                    zf.writestr(f"{carpeta}/{tabla}.csv", contenido)
                    resumen.append((carpeta, tabla, filas))
        zf.writestr("LEEME.txt", "Tus datos de CoreLux al " + datetime.datetime.now(ARGENTINA).strftime("%d/%m/%Y %H:%M") + "\n\n"
                    "Una carpeta por cuenta de Mercado Libre, con un archivo CSV por tipo de dato (se abren con Excel).\n"
                    "Las tablas sin datos no se incluyen. Los accesos a Mercado Libre (tokens) no se incluyen a propósito.\n\n"
                    + "\n".join(f"{c}/{t}.csv: {n} filas" for c, t, n in resumen) + "\n")
    return memoria.getvalue(), resumen

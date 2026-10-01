"""
Respaldo lógico propio de la base: exporta cada tabla de CoreLux a un CSV dentro de un zip, independiente del respaldo de Supabase.

    python respaldo.py                 # guarda respaldos/AAAAMMDD_HHMM.zip
    python respaldo.py --carpeta D:\\copias
    python respaldo.py --con-tokens    # incluye meli_tokens (cifrados con TOKEN_ENCRYPTION_KEY); por defecto NO se exportan

El zip contiene los datos de TODOS los usuarios: guardalo como se guarda una contraseña (fuera del repositorio y de la nube pública).
Para restaurar una tabla: crear la tabla con las migraciones y cargar el CSV, p. ej. en psql:
    \\copy ventas FROM 'ventas.csv' WITH (FORMAT csv, HEADER true)
"""
import argparse
import datetime
import io
import os
import sys
import zipfile
import db

# Tablas que administra Supabase (auth, storage, etc.) o que no son datos de la aplicación
SALTAR = {"schema_migrations"}
SENSIBLES = {"meli_tokens"}


def tablas_de_la_aplicacion(cursor):
    cursor.execute("""
        SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
    """)
    return [r[0] for r in cursor.fetchall()]


def exportar(carpeta="respaldos", con_tokens=False):
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".zip")
    resumen = []
    with db.conexion_admin() as conexion, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        cursor = conexion.cursor()
        for tabla in tablas_de_la_aplicacion(cursor):
            if tabla in SALTAR or (tabla in SENSIBLES and not con_tokens):
                continue
            salida = io.StringIO()
            with cursor.copy(f'COPY "{tabla}" TO STDOUT WITH (FORMAT csv, HEADER true)') as copia:
                for bloque in copia:
                    salida.write(bytes(bloque).decode("utf-8"))
            zf.writestr(f"{tabla}.csv", salida.getvalue())
            cursor.execute(f'SELECT count(*) FROM "{tabla}"')
            resumen.append((tabla, cursor.fetchone()[0]))
        zf.writestr("LEEME.txt", "Respaldo de CoreLux del " + datetime.datetime.now().isoformat(timespec="seconds") + "\n\n" +
                    "\n".join(f"{t}: {n} filas" for t, n in resumen) +
                    ("\n\nmeli_tokens NO incluida (usá --con-tokens).\n" if not con_tokens else "\n"))
    return destino, resumen


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Respaldo lógico de la base de CoreLux")
    p.add_argument("--carpeta", default="respaldos")
    p.add_argument("--con-tokens", action="store_true")
    a = p.parse_args()
    ruta, resumen = exportar(a.carpeta, a.con_tokens)
    print(f"Respaldo guardado en {ruta} ({os.path.getsize(ruta) // 1024} KB)")
    for t, n in resumen:
        print(f"  {t}: {n} filas")

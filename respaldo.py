"""
Respaldo lógico propio de la base: exporta cada tabla de CoreLux a un CSV dentro de un zip, independiente del respaldo de Supabase.

    python respaldo.py                     # guarda en ~/CoreLux-respaldos/AAAAMMDD_HHMM.zip(.cifrado)
    python respaldo.py --carpeta D:\\copias
    python respaldo.py --con-tokens        # incluye meli_tokens (cifrados con TOKEN_ENCRYPTION_KEY); por defecto NO se exportan
    python respaldo.py --generar-clave     # imprime una clave nueva para RESPALDO_CLAVE (guardala en el gestor de contraseñas)
    python respaldo.py --descifrar archivo.zip.cifrado

El zip contiene los datos de TODOS los usuarios, por eso:
  * por defecto se guarda FUERA de la carpeta del proyecto (y se niega a guardarse adentro: viajaría en git o en la imagen de Docker);
  * con RESPALDO_CLAVE definida en el .env se cifra (Fernet) y el zip en claro nunca se escribe a disco.
Sin esa clave guarda el zip sin cifrar y lo avisa. Perder la clave = perder el respaldo: guardala aparte del .env.
Para restaurar una tabla: crear la tabla con las migraciones y cargar el CSV, p. ej. en psql:
    \\copy ventas FROM 'ventas.csv' WITH (FORMAT csv, HEADER true)
"""
import argparse
import datetime
import io
import os
import sys
import zipfile

from cryptography.fernet import Fernet

# Tablas que administra Supabase (auth, storage, etc.) o que no son datos de la aplicación
SALTAR = {"schema_migrations"}
SENSIBLES = {"meli_tokens"}
RAIZ = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CIFRADO = ".cifrado"


def carpeta_por_defecto():
    return os.environ.get("RESPALDOS_CARPETA") or os.path.join(os.path.expanduser("~"), "CoreLux-respaldos")


def validar_carpeta(carpeta):
    """Un respaldo dentro del proyecto termina en git o en la imagen de Docker (ya pasó): se rechaza."""
    destino = os.path.realpath(carpeta)
    if os.path.commonpath([destino, RAIZ]) == RAIZ:
        raise ValueError(f"No se guarda un respaldo dentro del proyecto ({RAIZ}): tiene los datos de todos los usuarios. Elegí otra carpeta con --carpeta.")
    return destino


def cifrar(contenido, clave):
    return Fernet(clave).encrypt(contenido)


def descifrar(contenido, clave):
    return Fernet(clave).decrypt(contenido)


def tablas_de_la_aplicacion(cursor):
    cursor.execute("""
        SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
    """)
    return [r[0] for r in cursor.fetchall()]


def armar_zip(cursor, con_tokens=False):
    """Devuelve (bytes del zip, [(tabla, filas)]). Todo en memoria: el zip en claro no toca el disco."""
    memoria = io.BytesIO()
    resumen = []
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as zf:
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
    return memoria.getvalue(), resumen


def exportar(carpeta=None, con_tokens=False, clave=None):
    import db
    carpeta = validar_carpeta(carpeta or carpeta_por_defecto())
    os.makedirs(carpeta, exist_ok=True)
    with db.conexion_admin() as conexion:
        contenido, resumen = armar_zip(conexion.cursor(), con_tokens)
    nombre = datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".zip"
    if clave:
        contenido, nombre = cifrar(contenido, clave), nombre + EXTENSION_CIFRADO
    destino = os.path.join(carpeta, nombre)
    with open(destino, "wb") as f:
        f.write(contenido)
    return destino, resumen


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Respaldo lógico de la base de CoreLux")
    p.add_argument("--carpeta", default=None, help="por defecto ~/CoreLux-respaldos (o RESPALDOS_CARPETA); nunca dentro del proyecto")
    p.add_argument("--con-tokens", action="store_true")
    p.add_argument("--generar-clave", action="store_true", help="imprime una clave nueva para RESPALDO_CLAVE")
    p.add_argument("--descifrar", metavar="ARCHIVO", help="descifra un .zip.cifrado con RESPALDO_CLAVE y deja el .zip al lado")
    a = p.parse_args()

    if a.generar_clave:
        print(Fernet.generate_key().decode())
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv()
    clave = os.environ.get("RESPALDO_CLAVE") or None

    if a.descifrar:
        if not clave:
            sys.exit("Falta RESPALDO_CLAVE en el .env para descifrar.")
        salida = a.descifrar[:-len(EXTENSION_CIFRADO)] if a.descifrar.endswith(EXTENSION_CIFRADO) else a.descifrar + ".zip"
        with open(a.descifrar, "rb") as f, open(salida, "wb") as g:
            g.write(descifrar(f.read(), clave))
        print(f"Descifrado en {salida}")
        sys.exit(0)

    try:
        ruta, resumen = exportar(a.carpeta, a.con_tokens, clave)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Respaldo guardado en {ruta} ({os.path.getsize(ruta) // 1024} KB)" + ("" if clave else " — SIN CIFRAR: definí RESPALDO_CLAVE en el .env (python respaldo.py --generar-clave)"))
    for t, n in resumen:
        print(f"  {t}: {n} filas")

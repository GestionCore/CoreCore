"""
Sistema de migraciones versionadas para CoreLux.

Cómo usarlo:
    python migrate.py           → aplica todas las migraciones pendientes
    python migrate.py --status  → muestra qué migraciones están aplicadas
    python migrate.py --dry-run → muestra qué SQL correría, sin ejecutar

Cómo funciona:
  1. Crea (si no existe) la tabla `schema_migrations` en la base de datos.
  2. Lee todos los archivos .sql dentro de la carpeta `migrations/`,
     ordenados numéricamente por su prefijo (0001, 0002, ...).
  3. Corre los que no están en `schema_migrations` todavía, en orden.
  4. Registra cada uno al terminar.

Usa la conexión ADMIN (bypasses RLS) porque las migraciones son
operaciones de DBA — ALTER TABLE, CREATE TABLE, políticas de RLS.
El rol normal de la app no tiene permisos para este tipo de comandos.

Nota: cada archivo .sql debe ser idempotente (usar IF NOT EXISTS, IF EXISTS,
ON CONFLICT DO NOTHING, etc.) para poder correrse más de una vez sin romper
nada. Esto protege contra el caso en que la migración se aplicó
manualmente en Supabase antes de correr este script.
"""
import os
import sys
import re
import psycopg
import config

# La consola de Windows arranca en cp1252 por default, que no puede
# imprimir los emojis (✅ ⏳ etc.) que usa este script — mismo fix que
# ya tiene app.py, necesario acá también porque este script corre
# suelto, no dentro del proceso de Flask.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    aplicada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _obtener_conexion():
    """Conexión directa (no pooled) para el runner de migraciones."""
    if not config.DATABASE_URL_ADMIN:
        raise RuntimeError(
            "Falta DATABASE_URL_ADMIN en .env — "
            "las migraciones necesitan el rol admin para ALTER TABLE y CREATE TABLE."
        )
    return psycopg.connect(config.DATABASE_URL_ADMIN)


def _leer_migraciones():
    """Devuelve lista de (version, ruta) ordenada por versión."""
    if not os.path.isdir(MIGRATIONS_DIR):
        print(f"[Migrate] Carpeta de migraciones no encontrada: {MIGRATIONS_DIR}")
        return []
    archivos = []
    for nombre in os.listdir(MIGRATIONS_DIR):
        if not nombre.endswith(".sql"):
            continue
        match = re.match(r"^(\d{4})_", nombre)
        if not match:
            print(f"[Migrate] ⚠️ Ignorando {nombre} (no empieza con 4 dígitos)")
            continue
        version = match.group(1)
        archivos.append((version, os.path.join(MIGRATIONS_DIR, nombre), nombre))
    return sorted(archivos, key=lambda x: x[0])


def _aplicadas(cursor):
    """Set de versiones ya aplicadas."""
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {fila[0] for fila in cursor.fetchall()}


def correr(dry_run=False, solo_status=False):
    migraciones = _leer_migraciones()
    if not migraciones:
        print("[Migrate] No hay archivos .sql en migrations/")
        return

    con = _obtener_conexion()
    con.autocommit = False

    try:
        with con.cursor() as cur:
            # Crear tabla de control si no existe
            cur.execute(CREATE_MIGRATIONS_TABLE)
            con.commit()

            ya_aplicadas = _aplicadas(cur)

        if solo_status:
            print(f"\n{'VER':>6}  {'ESTADO':^10}  ARCHIVO")
            print("-" * 52)
            for version, ruta, nombre in migraciones:
                estado = "✅ aplicada" if version in ya_aplicadas else "⏳ pendiente"
                print(f"  {version}   {estado:^10}  {nombre}")
            print()
            return

        pendientes = [(v, r, n) for v, r, n in migraciones if v not in ya_aplicadas]

        if not pendientes:
            print("[Migrate] ✅ Base de datos al día — ninguna migración pendiente.")
            return

        print(f"[Migrate] {len(pendientes)} migración(es) pendiente(s):\n")

        for version, ruta, nombre in pendientes:
            with open(ruta, "r", encoding="utf-8") as f:
                sql = f.read().strip()

            if dry_run:
                print(f"  ── {nombre} (dry-run, no se ejecuta) ──")
                print(sql[:300] + ("..." if len(sql) > 300 else ""))
                print()
                continue

            print(f"  ▶ Aplicando {nombre}...")
            try:
                with con.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s) "
                        "ON CONFLICT DO NOTHING",
                        (version,),
                    )
                    con.commit()
                print(f"    ✅ {nombre} aplicada.")
            except Exception as e:
                con.rollback()
                print(f"    ❌ ERROR en {nombre}: {e}")
                print("    La migración fue revertida. Corregí el SQL y volvé a correr migrate.py.")
                sys.exit(1)

        if not dry_run:
            print(f"\n[Migrate] ✅ {len(pendientes)} migración(es) aplicada(s) correctamente.")

    finally:
        con.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    status = "--status" in sys.argv
    correr(dry_run=dry, solo_status=status)

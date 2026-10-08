"""
Verificación antes de desplegar. Corre, en este orden, lo que en la práctica encontró problemas que solo aparecían en producción:

  1. ruff                    nombres indefinidos, imports y variables sin uso
  2. pytest                  las pruebas de siempre
  3. pytest sin Redis        con REDIS_URL apuntando a un puerto sin servidor: Fly NO tiene Redis y esta PC sí, así que una lectura directa de la
                             caché pasaba todas las pruebas locales y habría dado 500 en todas las páginas
  4. recorrido de pantallas  todas las páginas GET con la primera cuenta de la base, también sin Redis y con las condiciones de Fly (FLY_APP_NAME,
                             pool chico). No escribe nada. Pasa si ninguna da error 5xx ni lanza una excepción.
  5. migraciones             avisa si hay migraciones sin aplicar (el deploy las aplica solo con release_command)

    python predeploy.py            # todo
    python predeploy.py --rapido   # sin el recorrido de pantallas (1-4 minutos menos)

Termina con código 0 si todo pasó y 1 si algo falló, así que sirve también en un script.
"""
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # la consola de Windows (cp1252) no puede imprimir los ✅/❌
except Exception:
    pass


def _python_del_proyecto():
    """El Python del venv del proyecto (donde están instaladas las dependencias); si no hay venv, el que corre este script."""
    for ruta in (("venv", "Scripts", "python.exe"), ("venv", "bin", "python"), (".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
        candidato = os.path.join(RAIZ, *ruta)
        if os.path.exists(candidato):
            return candidato
    return sys.executable


PY = _python_del_proyecto()
SIN_REDIS = {"REDIS_URL": "redis://localhost:6399/0"}
COMO_FLY = {**SIN_REDIS, "FLY_APP_NAME": "corecore", "FLY_REGION": "gru", "FLASK_DEBUG": "false", "DB_POOL_MAX": "3"}

# Rutas GET que necesitan parámetros o no son páginas: se omiten del recorrido.
OMITIR = ("/static", "/logout", "/callback", "/conectar", "/reconectar", "/webhook", "/admin", "/healthz")


def correr(titulo, comando, entorno=None, sin_omitidas=False):
    print(f"\n▶ {titulo}")
    t0 = time.time()
    r = subprocess.run(comando, cwd=RAIZ, env={**os.environ, "PYTHONIOENCODING": "utf-8", **(entorno or {})}, capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout + r.stderr).strip().splitlines()
    ok = r.returncode == 0
    # Una prueba omitida es una prueba que no corrió: pasó con las 16 de aislamiento entre cuentas (RLS) y la corrida igual daba verde
    if ok and sin_omitidas and salida and "skipped" in salida[-1]:
        ok = False
        salida.append("Hay pruebas OMITIDAS (¿falta DATABASE_URL en el .env?): antes de desplegar tienen que correr todas.")
    print(f"  {'✅' if ok else '❌'} {time.time() - t0:.0f} s — " + (salida[-1] if salida else ""))
    if not ok:
        print("\n".join("    " + l for l in salida[-25:]))
    return ok


RECORRIDO = r'''
import re, sys, traceback
sys.stdout.reconfigure(encoding="utf-8")
import app as a
import db
# Con la política estricta de scripts (seguridad.py, CSP_MODO) ningún <script> inline puede ir sin nonce ni quedar un manejador (onclick=…) o una URL javascript: en el HTML ya renderizado.
SCRIPT_SIN_NONCE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)(?![^>]*\bnonce=)[^>]*>")
MANEJADOR = re.compile(r"\son(?:click|change|input|submit|keyup|keydown|focus|blur)=[\"']|href=[\"']javascript:")
OMITIR = {omitir!r}
with db.conexion_admin() as con:
    cur = con.cursor(); cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1"); fila = cur.fetchone()
if not fila:
    print("sin cuentas en la base: no hay con qué recorrer"); sys.exit(0)
a.app.config["TESTING"] = True            # que una excepción llegue hasta acá en vez de quedar en una página de error
c = a.app.test_client()
with c.session_transaction() as s:
    s["usuario_id"], s["cuenta_id"] = fila
malas, total = [], 0
for rule in sorted(a.app.url_map.iter_rules(), key=lambda r: r.rule):
    if "GET" not in rule.methods or rule.arguments or rule.rule.startswith(OMITIR) or rule.rule in ("/healthz", "/healthz/db"):
        continue
    total += 1
    try:
        r = c.get(rule.rule)
        if r.status_code >= 500:
            malas.append(f"{{rule.rule}} -> {{r.status_code}}")
        elif r.status_code == 200 and r.mimetype == "text/html":
            pagina = r.get_data(as_text=True)
            if SCRIPT_SIN_NONCE.search(pagina):
                malas.append(f"{{rule.rule}} -> hay un <script> inline sin nonce (la política estricta lo bloquearía)")
            if MANEJADOR.search(pagina):
                malas.append(f"{{rule.rule}} -> hay un manejador escrito en el HTML (onclick=…) o una URL javascript: (la política estricta lo bloquearía)")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)[-1]
        malas.append(f"{{rule.rule}} -> {{type(e).__name__}}: {{str(e)[:100]}} ({{tb.filename.split(chr(92))[-1]}}:{{tb.lineno}})")
print(f"{{total}} pantallas recorridas, {{len(malas)}} con error")
for m in malas:
    print("  " + m)
sys.exit(1 if malas else 0)
'''


def _faltan_dependencias():
    r = subprocess.run([PY, "-c", "import psycopg, flask, pytest, ruff"], cwd=RAIZ, capture_output=True, text=True)
    if r.returncode == 0:
        return False
    print("❌ El Python que se está usando no tiene las dependencias instaladas:")
    print(f"   {PY}")
    print()
    print("   Este proyecto corre dentro de su venv. Desde la carpeta del proyecto:")
    print("     python -m venv venv                          (solo si todavía no existe la carpeta venv)")
    print("     venv\\Scripts\\activate")
    print("     pip install -r requirements-dev.txt")
    print("     python predeploy.py")
    return True


def main():
    rapido = "--rapido" in sys.argv
    print(f"Python: {PY}")
    if _faltan_dependencias():
        sys.exit(1)
    pasos = [
        correr("Lint (ruff)", [PY, "-m", "ruff", "check", "."]),
        correr("Pruebas", [PY, "-m", "pytest", "-q"], sin_omitidas=True),
        correr("Pruebas sin Redis", [PY, "-m", "pytest", "-q"], SIN_REDIS, sin_omitidas=True),
    ]
    if not rapido:
        pasos.append(correr("Recorrido de pantallas (sin Redis, como en Fly)", [PY, "-c", RECORRIDO.format(omitir=OMITIR)], COMO_FLY))
    # Migraciones pendientes: no falla el chequeo (el deploy las aplica), solo informa
    r = subprocess.run([PY, "migrate.py", "--status"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    pendientes = [l.strip() for l in r.stdout.splitlines() if "⏳" in l]
    print("\n▶ Migraciones")
    print(f"  {'ℹ️' if pendientes else '✅'} " + (f"{len(pendientes)} pendiente(s), el deploy las aplica solo: " + "; ".join(pendientes) if pendientes else "todas aplicadas"))
    fallo = not all(pasos)
    print("\n" + ("❌ Hay algo para arreglar antes de desplegar." if fallo else "✅ Todo en orden: se puede hacer fly deploy."))
    sys.exit(1 if fallo else 0)


if __name__ == "__main__":
    main()

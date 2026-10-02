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
PY = sys.executable
SIN_REDIS = {"REDIS_URL": "redis://localhost:6399/0"}
COMO_FLY = {**SIN_REDIS, "FLY_APP_NAME": "corecore", "FLY_REGION": "gru", "FLASK_DEBUG": "false", "DB_POOL_MAX": "3"}

# Rutas GET que necesitan parámetros o no son páginas: se omiten del recorrido.
OMITIR = ("/static", "/logout", "/callback", "/conectar", "/reconectar", "/webhook", "/admin", "/healthz")


def correr(titulo, comando, entorno=None):
    print(f"\n▶ {titulo}")
    t0 = time.time()
    r = subprocess.run(comando, cwd=RAIZ, env={**os.environ, "PYTHONIOENCODING": "utf-8", **(entorno or {})}, capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout + r.stderr).strip().splitlines()
    ok = r.returncode == 0
    print(f"  {'✅' if ok else '❌'} {time.time() - t0:.0f} s — " + (salida[-1] if salida else ""))
    if not ok:
        print("\n".join("    " + l for l in salida[-25:]))
    return ok


RECORRIDO = r'''
import sys, traceback
sys.stdout.reconfigure(encoding="utf-8")
import app as a
import db
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
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)[-1]
        malas.append(f"{{rule.rule}} -> {{type(e).__name__}}: {{str(e)[:100]}} ({{tb.filename.split(chr(92))[-1]}}:{{tb.lineno}})")
print(f"{{total}} pantallas recorridas, {{len(malas)}} con error")
for m in malas:
    print("  " + m)
sys.exit(1 if malas else 0)
'''


def main():
    rapido = "--rapido" in sys.argv
    pasos = [
        correr("Lint (ruff)", [PY, "-m", "ruff", "check", "."]),
        correr("Pruebas", [PY, "-m", "pytest", "-q"]),
        correr("Pruebas sin Redis", [PY, "-m", "pytest", "-q"], SIN_REDIS),
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

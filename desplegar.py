"""
Despliega CoreLux a Fly.io de forma segura. Un solo comando, en lugar de `fly deploy` a mano:

    python desplegar.py            # verificación completa + deploy + confirmación
    python desplegar.py --rapido   # salta el recorrido de pantallas de predeploy.py

Qué hace, y por qué (cada paso existe por un problema real):
  1. Se asegura de estar en la carpeta correcta, en la rama main, sin cambios sin guardar y con todo subido a GitHub. Un deploy sale de la carpeta donde se
     corre: se llegó a desplegar código viejo desde otra copia del proyecto.
  2. Corre predeploy.py (lint, pruebas, pruebas sin Redis, recorrido de pantallas).
  3. Despliega marcando la versión (el commit) dentro de la imagen.
  4. Espera a que producción responda con ESA versión y prueba las rutas clave. Si no responde bien, dice exactamente cómo volver atrás.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
URL = os.getenv("CORELUX_URL", "https://corelux.app").rstrip("/")
APP = "corecore"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _python():
    for ruta in (("venv", "Scripts", "python.exe"), ("venv", "bin", "python"), (".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
        candidato = os.path.join(RAIZ, *ruta)
        if os.path.exists(candidato):
            return candidato
    return sys.executable


def _fly():
    for nombre in ("fly", "flyctl"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    casa = os.path.join(os.path.expanduser("~"), ".fly", "bin")
    for nombre in ("fly.exe", "flyctl.exe", "fly", "flyctl"):
        ruta = os.path.join(casa, nombre)
        if os.path.exists(ruta):
            return ruta
    return None


def git(*args):
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


def fallar(mensaje):
    print(f"\n❌ {mensaje}")
    sys.exit(1)


def verificar_git():
    print("▶ Verificando carpeta y git")
    if not os.path.exists(os.path.join(RAIZ, "fly.toml")):
        fallar("Esta carpeta no tiene fly.toml: no es la del proyecto.")
    codigo, rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if codigo != 0:
        fallar("Esta carpeta no es un repositorio git (¿una copia suelta del proyecto?). Desplegá desde CoreLux-SaaS.")
    if rama != "main":
        fallar(f"Estás en la rama '{rama}', no en main.")
    _, sucio = git("status", "--porcelain")
    if sucio:
        fallar("Hay cambios sin guardar (commit):\n" + "\n".join("   " + l for l in sucio.splitlines()[:10]))
    git("fetch", "origin", "--quiet")
    _, local = git("rev-parse", "HEAD")
    _, remoto = git("rev-parse", "origin/main")
    if local != remoto:
        fallar("Lo que hay acá no coincide con GitHub (origin/main). Hacé `git pull` o `git push` y volvé a correr.")
    print(f"  ✅ main, sin cambios pendientes, igual a GitHub ({local[:12]})")
    return local[:12]


def pedir(ruta):
    req = urllib.request.Request(URL + ruta, headers={"User-Agent": "corelux-desplegar"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def esperar_version(version, minutos=4):
    print(f"\n▶ Esperando que producción quede en la versión {version}")
    limite = time.time() + minutos * 60
    ultimo = ""
    while time.time() < limite:
        codigo, cuerpo = pedir("/healthz")
        if codigo == 200:
            try:
                ultimo = json.loads(cuerpo).get("version", "")
            except ValueError:
                ultimo = "?"
            if ultimo == version:
                print("  ✅ producción responde con la versión nueva")
                return True
        time.sleep(5)
    print(f"  ❌ después de {minutos} min producción no responde con {version} (última versión vista: {ultimo or 'ninguna'})")
    return False


def probar_rutas():
    print("\n▶ Probando rutas clave")
    esperadas = [("/healthz", (200,)), ("/healthz/db", (200,)), ("/", (200, 302)), ("/planes", (200, 302)), ("/terminos", (200,)), ("/privacidad", (200,)),
                 ("/dashboard", (302,))]          # sin sesión, una pantalla protegida tiene que redirigir al ingreso (no dar error)
    ok = True
    for ruta, validos in esperadas:
        codigo, _ = pedir(ruta)
        bien = codigo in validos
        ok &= bien
        print(f"  {'✅' if bien else '❌'} {ruta} → {codigo}")
    return ok


def main():
    rapido = "--rapido" in sys.argv
    py, fly = _python(), _fly()
    if not fly:
        fallar("No encuentro el comando fly. Instalalo desde https://fly.io/docs/flyctl/install/")
    version = verificar_git()

    print("\n▶ predeploy.py")
    if subprocess.run([py, "predeploy.py"] + (["--rapido"] if rapido else []), cwd=RAIZ).returncode != 0:
        fallar("predeploy.py encontró problemas: no se despliega.")

    codigo, antes = pedir("/healthz")
    print(f"\n▶ Desplegando (fly deploy, versión {version})")
    if subprocess.run([fly, "deploy", "-a", APP, "--build-arg", f"GIT_SHA={version}"], cwd=RAIZ).returncode != 0:
        print("\nEl deploy falló. Fly mantiene las máquinas anteriores si no pasaron el chequeo de salud: mirá `fly status` y `fly logs`.")
        sys.exit(1)

    if esperar_version(version) and probar_rutas():
        print(f"\n✅ Desplegado y verificado: {URL} corre la versión {version}.")
        return
    print("\n❌ El deploy terminó pero producción no quedó bien. Para volver a la versión anterior:")
    print(f"     {os.path.basename(fly)} releases -a {APP} --image          (buscá la imagen de la release anterior)")
    print(f"     {os.path.basename(fly)} deploy -a {APP} --image <esa imagen>")
    print(f"   y mirá qué pasó con: {os.path.basename(fly)} logs -a {APP}")
    sys.exit(1)


if __name__ == "__main__":
    main()

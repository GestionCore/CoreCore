"""
Reglas de aislamiento entre cuentas que el código tiene que cumplir (las que costó encontrar): se revisan leyendo el código, sin base.
"""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# conexion_admin salta RLS. Solo se usa donde todavía no se sabe de quién es el pedido (webhooks, OAuth, scheduler), en las tareas de dueño
# (/admin, salud, borrado de cuenta, respaldos, migraciones, rotación de claves) y en token_manager (meli_tokens bloquea al rol normal).
USAN_ADMIN = {
    "app.py", "db.py", "feedback.py", "legal.py", "normalizar_horas.py", "predeploy.py", "respaldo.py", "rotar_clave.py", "salud_sistema.py", "scheduler.py", "seguridad.py",
    "salud_tokens.py", "sincronizador.py", os.path.join("auth", "registro.py"), os.path.join("auth", "token_manager.py"),
}


# Alta de usuario y de cuenta: la cuenta todavía no existe (o se está vinculando), así que no hay "cuenta activa" que fijar.
SIN_CUENTA_A_PROPOSITO = {(os.path.join("auth", "registro.py"), "crear_o_actualizar_login"), (os.path.join("auth", "registro.py"), "vincular_cuenta_adicional")}


def _fuentes():
    for patron in ("*.py", "auth/*.py", "tasks/*.py"):
        for ruta in glob.glob(os.path.join(RAIZ, patron)):
            yield os.path.relpath(ruta, RAIZ), open(ruta, encoding="utf-8").read()


def test_conexion_admin_solo_donde_esta_permitido():
    usan = {rel for rel, src in _fuentes() if re.search(r"conexion_admin\(|obtener_conexion_admin\(", src)}
    assert usan <= USAN_ADMIN, f"Usa conexion_admin sin estar en la lista de excepciones (revisar y documentar): {sorted(usan - USAN_ADMIN)}"


def test_migrate_y_los_scripts_de_dueno_no_importan_la_app_web():
    for rel in ("normalizar_horas.py", "rotar_clave.py", "respaldo.py"):
        src = open(os.path.join(RAIZ, rel), encoding="utf-8").read()
        assert not re.search(r"^\s*(import|from) app\b", src, re.M), rel


def test_los_modulos_que_abren_conexion_con_usuario_y_cuenta_siempre_pasan_la_cuenta():
    """Un `conexion_usuario(usuario_id)` suelto en una función que ya tiene cuenta_id deja la consulta sin el filtro de cuenta activa (RLS por cuenta)."""
    import ast
    malos = []
    for rel, src in _fuentes():
        if rel.startswith("tests") or rel == "db.py":
            continue
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nombres = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            nombres |= {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            if "cuenta_id" not in nombres or "usuario_id" not in nombres:
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "conexion_usuario"
                        and len(n.args) == 1 and not n.keywords and (rel, fn.name) not in SIN_CUENTA_A_PROPOSITO):
                    malos.append(f"{rel}:{n.lineno} ({fn.name})")
    assert not malos, "conexion_usuario sin cuenta_id aunque la función lo tiene: " + ", ".join(malos)

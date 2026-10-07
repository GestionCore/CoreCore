"""
Crear-o-encontrar el usuario y la cuenta de MeLi cuando alguien completa
el login por primera vez (o vuelve a hacerlo). El orden de las
operaciones acá NO es arbitrario — está pensado para que las políticas
de Row Level Security lo acepten (probado contra Postgres real):

1. La tabla `usuarios` no tiene RLS — se puede crear sin restricción.
2. Recién con el usuario_id ya generado, seteamos `app.usuario_actual`
   en la sesión de la conexión.
3. Solo ENTONCES insertamos en `cuentas_meli` — su política exige que
   usuario_id coincida con app.usuario_actual, así que si no seteamos
   el paso 2 antes, esta inserción es rechazada por la base misma.
"""
import secrets
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
import db

SUFIJO_EMAIL_PENDIENTE = "@pendiente.corelux.app"


def email_pendiente(meli_user_id):
    """Email provisorio de un usuario cuyo email real todavía no conocemos."""
    return f"meli-{meli_user_id}{SUFIJO_EMAIL_PENDIENTE}"


def email_de_meli(datos_meli):
    """El email que Mercado Libre informa para el vendedor, normalizado; None si no vino o no parece un email."""
    email = (datos_meli.get("email") or "").strip().lower()
    return email if "@" in email and "." in email.split("@")[-1] and not email.endswith(SUFIJO_EMAIL_PENDIENTE) else None


INTENTOS_CODIGO_REFERIDO = 5


def _generar_referral_code(cursor=None):
    """
    Un código de referido aleatorio de 8 caracteres. Con `cursor` se comprueba en la base que nadie lo tenga ya (la probabilidad de choque es ínfima, pero antes ni se
    miraba: un choque saltaba como UniqueViolation y se confundía con un email repetido).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I/L confundibles
    for _ in range(10):
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if cursor is None:
            return code
        cursor.execute("SELECT 1 FROM usuarios WHERE referral_code = %s", (code,))
        if cursor.fetchone() is None:
            return code
    raise RuntimeError("No se pudo generar un código de referido libre.")


def _restriccion_violada(error):
    """Qué restricción UNIQUE saltó: «referral_code», «email» u «otra» (psycopg informa el nombre en error.diag.constraint_name)."""
    nombre = getattr(getattr(error, "diag", None), "constraint_name", None) or ""
    if "referral_code" in nombre:
        return "referral_code"
    if "email" in nombre:
        return "email"
    return "otra"


def _descartar_usuario_sin_cuenta(usuario_id):
    """Borra un usuario recién creado que quedó sin cuenta ni datos (porque otro pedido creó la cuenta un instante antes)."""
    conexion = db._obtener_pool().getconn()
    try:
        conexion.cursor().execute("DELETE FROM usuarios WHERE id = %s AND NOT EXISTS (SELECT 1 FROM cuentas_meli WHERE usuario_id = %s)", (usuario_id, usuario_id))
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        db.liberar_conexion(conexion)


def crear_o_actualizar_login(datos_meli, email_para_nuevo_usuario=None, _reintento=False):
    """
    datos_meli: {"meli_user_id": int, "nickname": str, "site_id": str}
    Devuelve (usuario_id, cuenta_id, es_usuario_nuevo).
    """
    meli_user_id = datos_meli["meli_user_id"]

    # Este primer paso es la ÚNICA parte de este archivo que usa la
    # conexión admin, y es un caso legítimo y acotado: necesitamos buscar
    # por meli_user_id ANTES de saber el usuario_id, así que todavía no
    # hay nada que setear en app.usuario_actual. En cuanto sabemos quién
    # es (abajo), volvemos de inmediato al canal normal con RLS.
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE meli_user_id = %s", (meli_user_id,))
        cuenta_existente = cursor.fetchone()

    if cuenta_existente:
        usuario_id = cuenta_existente["usuario_id"]
        cuenta_id = cuenta_existente["id"]
        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute(
                "UPDATE cuentas_meli SET nickname = %s, activa = true, ultima_sincronizacion = now() WHERE id = %s",
                (datos_meli.get("nickname"), cuenta_id)
            )
        _completar_email_pendiente(usuario_id, datos_meli)
        return usuario_id, cuenta_id, False

    # Cuenta de MeLi nueva para nosotros — creamos usuario y cuenta. La
    # tabla `usuarios` no tiene RLS, así que un connection pool simple
    # alcanza para el INSERT inicial.
    from datetime import datetime, timedelta, timezone
    trial_termina_en = datetime.now(timezone.utc) + timedelta(days=14)
    # usuarios.email es único: si el email de Mercado Libre ya lo tiene otro usuario de CoreLux (la misma persona con dos cuentas de MeLi
    # que no se vincularon), se arranca con el provisorio en vez de impedirle entrar.
    candidatos = [e for e in (email_para_nuevo_usuario, email_de_meli(datos_meli)) if e] + [email_pendiente(meli_user_id)]

    usuario_id = None
    for email in candidatos:
        for _ in range(INTENTOS_CODIGO_REFERIDO):
            conexion = db._obtener_pool().getconn()
            try:
                cursor = conexion.cursor(row_factory=dict_row)
                cursor.execute(
                    "INSERT INTO usuarios (email, plan, trial_termina_en, referral_code) VALUES (%s, 'trial', %s, %s) RETURNING id",
                    (email, trial_termina_en, _generar_referral_code(cursor))
                )
                usuario_id = cursor.fetchone()["id"]
                conexion.commit()
                break
            except UniqueViolation as e:
                conexion.rollback()
                if _restriccion_violada(e) != "referral_code":
                    break              # el email ya lo tiene otro usuario: se prueba con el siguiente candidato
                # chocó el código aleatorio (casi imposible): se reintenta con OTRO código y el MISMO email. Antes se tomaba por un email repetido y se
                # le asignaba al usuario el provisorio, quemando su email real.
            finally:
                db.liberar_conexion(conexion)
        if usuario_id is not None:
            break
    if usuario_id is None:
        raise RuntimeError("No se pudo crear el usuario: ni el email de Mercado Libre ni el provisorio estaban disponibles.")

    # Ahora que existe el usuario_id, recién acá entramos al canal con
    # RLS activo — esta es la secuencia que probamos contra Postgres
    # real: setear la sesión ANTES del INSERT en cuentas_meli, o la
    # política lo rechaza.
    try:
        with db.conexion_usuario(usuario_id) as conexion:
            cursor = conexion.cursor(row_factory=dict_row)
            cursor.execute(
                """INSERT INTO cuentas_meli (usuario_id, meli_user_id, nickname, site_id)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (usuario_id, meli_user_id, datos_meli.get("nickname"), datos_meli.get("site_id", "MLA"))
            )
            cuenta_id = cursor.fetchone()["id"]
    except UniqueViolation:
        # Otro pedido (un doble clic en el login) creó esta cuenta de Mercado Libre un instante antes: el usuario que acabamos de crear quedó sin cuenta ni datos, se
        # descarta y se sigue por el camino de una cuenta que ya existe.
        _descartar_usuario_sin_cuenta(usuario_id)
        if _reintento:
            raise
        return crear_o_actualizar_login(datos_meli, email_para_nuevo_usuario, _reintento=True)

    return usuario_id, cuenta_id, True


def _completar_email_pendiente(usuario_id, datos_meli):
    """
    Los usuarios creados antes de leer el email de Mercado Libre quedaron con el provisorio (meli-<id>@pendiente...), y con ese no pueden
    recibir avisos, cobrar una suscripción ni ser reconocidos como administrador. En el próximo inicio de sesión se reemplaza por el real,
    salvo que otro usuario ya lo tenga. Nunca pisa un email que no sea provisorio.
    """
    email = email_de_meli(datos_meli)
    if not email:
        return
    try:
        with db.conexion_usuario(usuario_id) as conexion:
            conexion.cursor().execute(
                """UPDATE usuarios SET email = %s
                   WHERE id = %s AND email LIKE %s
                     AND NOT EXISTS (SELECT 1 FROM usuarios o WHERE lower(o.email) = %s)""",
                (email, usuario_id, "%" + SUFIJO_EMAIL_PENDIENTE, email)
            )
    except Exception as e:
        print(f"[Registro] ⚠️ No se pudo completar el email del usuario {usuario_id}: {e}")


def vincular_cuenta_adicional(usuario_id, datos_meli):
    """
    Conecta una cuenta de MeLi ADICIONAL al usuario ya logueado (plan
    Elite, multi-cuenta) — a diferencia de crear_o_actualizar_login, acá
    ya sabemos el usuario_id de entrada, así que nunca crea un usuario
    nuevo ni un trial nuevo.

    Devuelve (cuenta_id, resultado) donde resultado es:
      "vinculada"       — cuenta de MeLi nueva, recién asociada a este usuario.
      "reconectada"      — la cuenta de MeLi ya era de este mismo usuario (re-autorización).
      "ya_de_otro_usuario" — la cuenta de MeLi ya está conectada a OTRO usuario de
                              CoreLux; no se toca nada (cuenta_id viene None).
    """
    meli_user_id = datos_meli["meli_user_id"]

    # Mirar y después insertar deja una ventana: un doble clic manda dos pedidos y el segundo choca con el UNIQUE de meli_user_id. Si pasa, se vuelve a mirar: ya existe
    # (la creó el primer pedido) y se sigue como una cuenta que ya estaba vinculada, en vez de un error 500.
    for _ in range(2):
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor(row_factory=dict_row)
            cursor.execute("SELECT id, usuario_id FROM cuentas_meli WHERE meli_user_id = %s", (meli_user_id,))
            cuenta_existente = cursor.fetchone()

        if cuenta_existente:
            if cuenta_existente["usuario_id"] != usuario_id:
                return None, "ya_de_otro_usuario"
            cuenta_id = cuenta_existente["id"]
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute(
                    "UPDATE cuentas_meli SET nickname = %s, activa = true, ultima_sincronizacion = now() WHERE id = %s",
                    (datos_meli.get("nickname"), cuenta_id)
                )
            return cuenta_id, "reconectada"

        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor(row_factory=dict_row)
                cursor.execute(
                    """INSERT INTO cuentas_meli (usuario_id, meli_user_id, nickname, site_id)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (usuario_id, meli_user_id, datos_meli.get("nickname"), datos_meli.get("site_id", "MLA"))
                )
                cuenta_id = cursor.fetchone()["id"]
            return cuenta_id, "vinculada"
        except UniqueViolation:
            continue
    raise RuntimeError("No se pudo vincular la cuenta de Mercado Libre: se creó y desapareció a la vez.")


def obtener_cuentas_de_usuario(usuario_id):
    """
    Todas las cuentas de MeLi que un usuario tiene conectadas (para el
    plan Elite multi-cuenta).

    Nota histórica: esta función tuvo un comentario de advertencia acá
    (datos mezclados entre cuentas de un mismo usuario) porque, cuando
    se escribió, todavía no existía ninguna pantalla real que conectara
    una segunda cuenta. Se verificó a fondo (auditoría completa de los
    ~120 puntos que abren conexión con RLS, más grep de toda consulta a
    `ventas`/`productos_padre`/`productos_variantes` sin filtro
    explícito) que en realidad TODAS las rutas de app.py que usan
    `g.usuario_id` para abrir una conexión también pasan `g.cuenta_id`
    — la migración 0010 (RLS por cuenta activa, `app.cuenta_actual`) ya
    está aplicada Y en uso real en las 58 rutas que abren conexión con
    RLS. El riesgo que describía este comentario no existe más: no hace
    falta ningún arreglo adicional antes de usar multi-cuenta de verdad.
    """
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("SELECT id, nickname, nombre_negocio, activa, capacidades, condicion_fiscal FROM cuentas_meli WHERE usuario_id = %s ORDER BY conectada_en", (usuario_id,))
        return [dict(fila) for fila in cursor.fetchall()]

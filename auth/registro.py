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
from psycopg.rows import dict_row
import db


def crear_o_actualizar_login(datos_meli, email_para_nuevo_usuario=None):
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
        return usuario_id, cuenta_id, False

    # Cuenta de MeLi nueva para nosotros — creamos usuario y cuenta. La
    # tabla `usuarios` no tiene RLS, así que un connection pool simple
    # alcanza para el INSERT inicial.
    from datetime import datetime, timedelta, timezone
    trial_termina_en = datetime.now(timezone.utc) + timedelta(days=14)
    email = email_para_nuevo_usuario or f"meli-{meli_user_id}@pendiente.corelux.app"

    conexion = db._obtener_pool().getconn()
    try:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute(
            "INSERT INTO usuarios (email, plan, trial_termina_en) VALUES (%s, 'trial', %s) RETURNING id",
            (email, trial_termina_en)
        )
        usuario_id = cursor.fetchone()["id"]
        conexion.commit()
    finally:
        db.liberar_conexion(conexion)

    # Ahora que existe el usuario_id, recién acá entramos al canal con
    # RLS activo — esta es la secuencia que probamos contra Postgres
    # real: setear la sesión ANTES del INSERT en cuentas_meli, o la
    # política lo rechaza.
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute(
            """INSERT INTO cuentas_meli (usuario_id, meli_user_id, nickname, site_id)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (usuario_id, meli_user_id, datos_meli.get("nickname"), datos_meli.get("site_id", "MLA"))
        )
        cuenta_id = cursor.fetchone()["id"]

    return usuario_id, cuenta_id, True


def obtener_cuentas_de_usuario(usuario_id):
    """Todas las cuentas de MeLi que un usuario tiene conectadas (para el plan Elite multi-cuenta)."""
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor(row_factory=dict_row)
        cursor.execute("SELECT id, nickname, nombre_negocio, activa FROM cuentas_meli WHERE usuario_id = %s ORDER BY conectada_en", (usuario_id,))
        return [dict(fila) for fila in cursor.fetchall()]

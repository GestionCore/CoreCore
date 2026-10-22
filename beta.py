"""
Beta cerrada: entrada con invitación y lista de espera (migración 0051).

Regla: quien ya tiene cuenta entra siempre. Una cuenta NUEVA de Mercado Libre solo se crea si llega con un código de invitación válido
(`session["beta_codigo"]`, que deja /beta/entrar). El código se consume de forma atómica justo antes de crear la cuenta y se libera si la creación falla.
Se apaga con BETA_SOLO_INVITADOS=0 (config.py) para abrir el registro.

Usa `conexion_admin` a propósito: son tablas del sistema, sin dueño por cuenta, y ninguna pantalla común las puede leer.
"""
import re
import secrets

import config
import db

# Sin 0/O/1/I/L: el código se lee por teléfono o se copia desde un mensaje.
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO_GRUPO = 4
GRUPOS = 2
PREFIJO = "CL"

MOTIVOS = {
    "no_existe": "Ese código no es válido. Revisalo: se escribe tal como te lo mandamos.",
    "agotado": "Ese código ya se usó. Si lo compartiste con alguien más, escribinos y te mandamos otro.",
    "vencido": "Ese código venció. Escribinos y te mandamos uno nuevo.",
    "inactivo": "Ese código ya no está activo. Escribinos y te mandamos uno nuevo.",
    "vacio": "Escribí el código de invitación que te mandamos.",
}


def normalizar_codigo(texto):
    """«cl-7k4m 9qxd» → «CL-7K4M-9QXD». Sin letras ni números válidos devuelve ''."""
    limpio = re.sub(r"[^A-Za-z0-9]", "", texto or "").upper()
    if not limpio:
        return ""
    if limpio.startswith(PREFIJO) and len(limpio) == len(PREFIJO) + LARGO_GRUPO * GRUPOS:
        cuerpo = limpio[len(PREFIJO):]
        return "-".join([PREFIJO] + [cuerpo[i:i + LARGO_GRUPO] for i in range(0, len(cuerpo), LARGO_GRUPO)])
    return limpio[:40]


def generar_codigo():
    cuerpo = ["".join(secrets.choice(ALFABETO) for _ in range(LARGO_GRUPO)) for _ in range(GRUPOS)]
    return "-".join([PREFIJO] + cuerpo)


def _motivo(fila):
    """Por qué una invitación no sirve, o None si sirve. `fila` = (activa, usos, usos_max, vencida)."""
    activa, usos, usos_max, vencida = fila
    if not activa:
        return "inactivo"
    if vencida:
        return "vencido"
    if usos >= usos_max:
        return "agotado"
    return None


def validar(codigo):
    """(ok, motivo): si el código se puede usar ahora. Solo mira, no consume nada."""
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return False, "vacio"
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT activa, usos, usos_max, COALESCE(expira_en < now(), false) FROM beta_invitaciones WHERE codigo = %s", (codigo,))
        fila = cursor.fetchone()
    if not fila:
        return False, "no_existe"
    motivo = _motivo(fila)
    return (motivo is None), motivo


def reservar(codigo):
    """
    Consume un uso del código de forma atómica (dos personas con el mismo código no pasan las dos si solo queda un uso).
    Devuelve el id de la invitación o None si ya no sirve.
    """
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return None
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """UPDATE beta_invitaciones SET usos = usos + 1
               WHERE codigo = %s AND activa AND usos < usos_max AND (expira_en IS NULL OR expira_en > now())
               RETURNING id""",
            (codigo,),
        )
        fila = cursor.fetchone()
    return fila[0] if fila else None


def liberar(invitacion_id):
    """Devuelve el uso reservado cuando la cuenta no llegó a crearse."""
    with db.conexion_admin() as conexion:
        conexion.cursor().execute("UPDATE beta_invitaciones SET usos = GREATEST(usos - 1, 0) WHERE id = %s", (invitacion_id,))


def registrar_canje(invitacion_id, usuario_id):
    with db.conexion_admin() as conexion:
        conexion.cursor().execute("INSERT INTO beta_canjes (invitacion_id, usuario_id) VALUES (%s, %s)", (invitacion_id, usuario_id))


def cuenta_existe(meli_user_id):
    """¿Esa cuenta de Mercado Libre ya está en CoreLux? Si sí, entra sin invitación (es una persona que vuelve)."""
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT 1 FROM cuentas_meli WHERE meli_user_id = %s", (meli_user_id,))
        return cursor.fetchone() is not None


def crear_invitacion(nota=None, usos_max=1, dias=None):
    """Genera una invitación nueva (la crea el administrador). Devuelve el código."""
    usos_max = max(1, min(int(usos_max or 1), 50))
    for _ in range(8):
        codigo = generar_codigo()
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute(
                """INSERT INTO beta_invitaciones (codigo, nota, usos_max, expira_en)
                   VALUES (%s, %s, %s, CASE WHEN %s::int IS NULL THEN NULL ELSE now() + make_interval(days => %s::int) END)
                   ON CONFLICT (codigo) DO NOTHING RETURNING codigo""",
                (codigo, (nota or "").strip()[:200] or None, usos_max, dias, dias),
            )
            fila = cursor.fetchone()
        if fila:
            return fila[0]
    raise RuntimeError("No se pudo generar un código nuevo.")


def desactivar(invitacion_id):
    with db.conexion_admin() as conexion:
        conexion.cursor().execute("UPDATE beta_invitaciones SET activa = false WHERE id = %s", (invitacion_id,))


def listar_invitaciones():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """SELECT i.id, i.codigo, i.nota, i.usos, i.usos_max, i.activa, i.expira_en, i.creada_en,
                      COALESCE(i.expira_en < now(), false) AS vencida
               FROM beta_invitaciones i ORDER BY i.creada_en DESC LIMIT 200"""
        )
        filas = cursor.fetchall()
    return [{"id": f[0], "codigo": f[1], "nota": f[2], "usos": f[3], "usos_max": f[4], "activa": f[5], "expira_en": f[6], "creada_en": f[7],
             "estado": _estado_visible((f[5], f[3], f[4], f[8]))} for f in filas]


def _estado_visible(fila):
    motivo = _motivo(fila)
    return {None: "disponible", "inactivo": "desactivada", "vencido": "vencida", "agotado": "usada"}[motivo]


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def anotar_en_espera(email, rubro=None, mensaje=None):
    """
    Pone un mail en la lista de espera. Devuelve True si quedó anotado (o ya estaba: no se le dice a nadie si ese mail ya estaba)
    y False si el mail no parece uno.
    """
    email = (email or "").strip()[:254]
    if not EMAIL_RE.match(email):
        return False
    with db.conexion_admin() as conexion:
        conexion.cursor().execute(
            "INSERT INTO beta_espera (email, rubro, mensaje) VALUES (%s, %s, %s) ON CONFLICT (lower(email)) DO NOTHING",
            (email, (rubro or "").strip()[:120] or None, (mensaje or "").strip()[:500] or None),
        )
    return True


def listar_espera():
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT id, email, rubro, mensaje, creado_en FROM beta_espera ORDER BY creado_en DESC LIMIT 300")
        return [{"id": f[0], "email": f[1], "rubro": f[2], "mensaje": f[3], "creado_en": f[4]} for f in cursor.fetchall()]


def hay_que_pedir_invitacion():
    """¿La beta exige invitación para crear una cuenta nueva? (config.BETA_SOLO_INVITADOS)"""
    return bool(config.BETA_SOLO_INVITADOS)

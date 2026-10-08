"""
Horario de corte del despacho, sin inventar nada.

· Correo (`drop_off`): Mercado Libre informa un corte POR DÍA de la semana en GET /users/{id}/shipping/schedule/drop_off (`schedule.<dia>.work` + `detail[0].cutoff`).
  La semana se guarda en `cuentas_meli.horario_corte` (JSONB) y se refresca una vez por día. Si Mercado Libre no lo informa, se dice «Corte de correo no informado»:
  nunca se muestra un horario supuesto (antes el valor de reserva era un 11:00 fijo que no coincidía con el real, 13:00).
· Flex (`self_service`): la API NO expone ningún horario de corte (el schedule de self_service responde 404 y los endpoints de configuración de Flex no existen).
  Lo carga la persona en Mi cuenta (`configuracion_cuenta`, clave `flex_hora_corte`); si no lo cargó se muestra «Corte Flex: No configurado (Ajustar)».
"""
import json
import re
from datetime import datetime, timedelta, timezone

import db
import logistica

CLAVE_FLEX = "flex_hora_corte"
HORAS_DE_VIGENCIA = 24
_HORA = re.compile(r"^(\d{1,2})(?:[:.h](\d{2})|h)?$")


def normalizar_hora(texto):
    """«HH:MM» (00:00 a 23:59) a partir de «14», «14:30», «9:05» o «14.30»; None si no es una hora válida."""
    coincide = _HORA.match(str(texto or "").strip().lower().replace(" ", ""))
    if not coincide:
        return None
    hora, minutos = int(coincide.group(1)), int(coincide.group(2) or 0)
    if hora > 23 or minutos > 59:
        return None
    return f"{hora:02d}:{minutos:02d}"


def semana_desde_schedule(datos):
    """
    {dia: «HH:MM» | None} a partir de la respuesta REAL de /users/{id}/shipping/schedule/drop_off. None = ese día no hay retiro (`work: false`) o no informa corte.
    Forma real: {"schedule": {"monday": {"work": true, "detail": [{"cutoff": "13:00", "sla": "same_day", ...}]}, "saturday": {"work": false, ...}, ...}}
    """
    programa = (datos or {}).get("schedule") or {}
    semana = {}
    for dia in logistica.DIAS_SEMANA_EN:
        info = programa.get(dia) or {}
        detalle = info.get("detail") or []
        corte = normalizar_hora((detalle[0] or {}).get("cutoff")) if (info.get("work") and detalle) else None
        semana[dia] = corte
    return semana


def corte_del_dia(horario, fecha):
    """
    Corte de Correo del día de `fecha` (date o «AAAA-MM-DD»): («HH:MM», 'informado') · (None, 'sin_retiro') si ese día no hay retiro · (None, 'no_informado') si
    Mercado Libre no informa el horario de esta cuenta.
    """
    semana = (horario or {}).get("drop_off")
    if not isinstance(semana, dict) or not semana:
        return None, "no_informado"
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
    corte = semana.get(logistica.DIAS_SEMANA_EN[fecha.weekday()])
    return (corte, "informado") if corte else (None, "sin_retiro")


def resolver_cortes(horario, flex_hora, fecha):
    """
    Todo lo que necesita la pantalla de Despacho para la fecha `fecha`:
      correo: {"hora": «HH:MM» | None, "estado": informado | sin_retiro | no_informado}
      flex: «HH:MM» | None (None = la persona todavía no lo cargó)
      hora_agrupacion: hora entera (0-24) con la que se arma el día de despacho. Es el corte de Correo si se conoce; si no, el de Flex que cargó la persona; si no hay ninguno,
      24 = día calendario (sin inventar un corte).
    """
    hora_correo, estado = corte_del_dia(horario, fecha)
    flex = normalizar_hora(flex_hora)
    origen = hora_correo or flex
    return {"correo": {"hora": hora_correo, "estado": estado}, "flex": flex, "hora_agrupacion": int(origen[:2]) if origen else 24}


def cortes_js(cortes):
    """Lista para el contador de la pantalla: solo los cortes que se conocen."""
    lista = []
    if cortes["correo"]["hora"]:
        lista.append({"nombre": "Correo", "hora": cortes["correo"]["hora"]})
    if cortes["flex"]:
        lista.append({"nombre": "Flex", "hora": cortes["flex"]})
    return lista


# ── Lectura y guardado (siempre con la conexión del usuario y la cuenta activa: RLS) ───────────────────────────────────────────────────────

def leer_flex(cursor, cuenta_id):
    cursor.execute("SELECT valor FROM configuracion_cuenta WHERE cuenta_id = %s AND clave = %s", (cuenta_id, CLAVE_FLEX))
    fila = cursor.fetchone()
    return normalizar_hora(fila[0]) if fila else None


def guardar_flex(cursor, cuenta_id, texto):
    """Guarda la hora de corte de Flex. Texto vacío = la quita. Devuelve «HH:MM», None si se quitó, o False si no era una hora válida."""
    if str(texto or "").strip() == "":
        cursor.execute("DELETE FROM configuracion_cuenta WHERE cuenta_id = %s AND clave = %s", (cuenta_id, CLAVE_FLEX))
        return None
    hora = normalizar_hora(texto)
    if hora is None:
        return False
    cursor.execute("""
        INSERT INTO configuracion_cuenta (cuenta_id, clave, valor) VALUES (%s, %s, %s)
        ON CONFLICT (cuenta_id, clave) DO UPDATE SET valor = excluded.valor
    """, (cuenta_id, CLAVE_FLEX, hora))
    return hora


def _esta_vigente(horario, ahora):
    try:
        return ahora - datetime.fromisoformat(horario["actualizado_en"]) < timedelta(hours=HORAS_DE_VIGENCIA)
    except (KeyError, TypeError, ValueError):
        return False


def horario_de_correo(usuario_id, cuenta_id, access_token, seller_id, ahora=None, consultar=None):
    """
    El horario guardado de la cuenta; si no hay o tiene más de un día, se vuelve a pedir a Mercado Libre y se guarda. Si la consulta FALLA se sigue con lo último
    guardado (un hipo de la API no borra el horario). Devuelve {"drop_off": {dia: hora|None} | None, "actualizado_en": iso} o None si nunca se pudo saber.
    """
    ahora = ahora or datetime.now(timezone.utc)
    consultar = consultar or logistica.obtener_horario_semanal
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT horario_corte FROM cuentas_meli WHERE id = %s", (cuenta_id,))
            fila = cursor.fetchone()
    except Exception as e:                       # la migración 0041 todavía no está aplicada: la pantalla funciona igual, sin horario de Correo
        print(f"[DespachoCorte] ℹ️ No se pudo leer el horario guardado: {e}")
        return None
    guardado = fila[0] if fila and isinstance(fila[0], dict) else None
    if guardado and _esta_vigente(guardado, ahora):
        return guardado
    if not (access_token and seller_id):
        return guardado
    estado, semana = consultar(access_token, seller_id, "drop_off")
    if estado == "error":
        return guardado
    nuevo = {"drop_off": semana if estado == "ok" else None, "actualizado_en": ahora.isoformat()}      # 'no_tiene': MeLi dice que no hay horario de Correo; se recuerda un día
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        conexion.cursor().execute("UPDATE cuentas_meli SET horario_corte = %s::jsonb WHERE id = %s", (json.dumps(nuevo), cuenta_id))
    return nuevo


def cortes_para(usuario_id, cuenta_id, access_token, seller_id, fecha):
    """Los cortes de la fecha pedida para esta cuenta (ver resolver_cortes)."""
    horario = horario_de_correo(usuario_id, cuenta_id, access_token, seller_id)
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        flex_hora = leer_flex(conexion.cursor(), cuenta_id)
    return resolver_cortes(horario, flex_hora, fecha)

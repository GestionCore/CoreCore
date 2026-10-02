"""Onboarding — encuesta de una sola vez la primera vez que alguien conecta su cuenta."""
import db

OPCIONES_PRIORIDAD = {
    "ganancia": "Ganancia real y rentabilidad",
    "stock": "Stock y quiebres",
    "publicidad": "Publicidad y retorno de inversión",
    "competencia": "Competencia y tendencias",
    "todo": "Un poco de todo, sin prioridad fija",
}
OPCIONES_EXPERIENCIA = {
    "nuevo": "Recién estoy empezando",
    "en_crecimiento": "Vendo hace menos de un año",
    "consolidado": "Vendo hace más de un año",
}
OPCIONES_PANTALLA = {
    "dashboard": "Un resumen general de todo",
    "stock": "Mi catálogo y stock",
    "metricas": "Mis números de Ganancia Real",
}

RUTA_POR_PANTALLA = {"dashboard": "dashboard_personalizable", "stock": "landing", "metricas": "metricas_vista"}


def guardar_respuestas(usuario_id, prioridades, experiencia, pantalla):
    """
    `prioridades` es una lista (pedido explícito: esta pregunta admite
    elegir más de una, a diferencia de las otras dos que son de una
    sola respuesta por naturaleza — hace cuánto vendés y qué pantalla
    preferís no tienen sentido como multi-select). Se guarda como texto
    separado por comas en la misma columna de siempre.
    """
    if not prioridades or any(p not in OPCIONES_PRIORIDAD for p in prioridades):
        return False
    if experiencia not in OPCIONES_EXPERIENCIA or pantalla not in OPCIONES_PANTALLA:
        return False
    prioridad_guardada = ",".join(prioridades)
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            UPDATE usuarios SET onboarding_completo = true, prioridad_principal = %s,
                                 experiencia_meli = %s, pantalla_preferida = %s
            WHERE id = %s
        """, (prioridad_guardada, experiencia, pantalla, usuario_id))
    return True


def obtener_endpoint_home(usuario_id):
    """A qué pantalla mandar a este usuario cuando entra — según lo que eligió en la encuesta."""
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT pantalla_preferida FROM usuarios WHERE id = %s", (usuario_id,))
        fila = cursor.fetchone()
    pantalla = fila[0] if fila and fila[0] else "stock"
    return RUTA_POR_PANTALLA.get(pantalla, "landing")


PORCENTAJE_COSTOS_COMPLETO = 90      # con el 90 % de las publicaciones activas con costo, el paso se da por hecho (siempre queda alguna promo sin costo)


def armar_checklist(onboarding_completo, sync_completa, activas, con_costo, tiene_gastos, tiene_ventas, capacidades=None, umbrales=None):
    """
    Los pasos de "Completá tu perfil", con su estado. Los dos primeros ya están resueltos si la persona llegó hasta acá (login_requerido no deja
    pasar sin eso). El de costos se da por hecho cuando casi todas las publicaciones activas tienen costo: con uno solo cargado la ganancia sigue
    inflada. El de Flex solo aparece si la cuenta tiene Flex confirmado (capacidades.flex True): lo que no aplica a un rubro no se pide.
    """
    capacidades = capacidades or {}
    pct_costos = round(con_costo / activas * 100) if activas else 0
    pasos = [
        {"id": "onboarding", "texto": "Contanos cómo vendés (encuesta inicial)", "completo": bool(onboarding_completo), "link": None},
        {"id": "sync", "texto": "Primera sincronización con Mercado Libre", "completo": bool(sync_completa), "link": None},
        {"id": "costos", "texto": "Cargar el costo de fabricación de tus productos", "completo": activas > 0 and pct_costos >= PORCENTAJE_COSTOS_COMPLETO,
         "link": "/costos", "detalle": f"{con_costo} de {activas} con costo cargado: sin costo, la ganancia sale inflada." if activas else None},
    ]
    if capacidades.get("flex") is True:
        sin_precio = all(u.get("precio") is None for u in umbrales) if isinstance(umbrales, list) else True
        pasos.append({"id": "flex", "texto": "Cargar el costo de tus entregas Flex", "completo": not sin_precio, "link": "/costos#entrega-flex",
                      "detalle": "Mercado Libre informa $0 de envío en Flex: el costo real lo cobra tu logística."})
    pasos += [
        {"id": "gastos", "texto": "Cargar tus gastos fijos (alquiler, bolsas, etc.)", "completo": bool(tiene_gastos), "link": "/costos"},
        {"id": "ventas", "texto": "Tener al menos una venta sincronizada", "completo": bool(tiene_ventas), "link": "/metricas"},
    ]
    completos = sum(1 for p in pasos if p["completo"])
    return {"pasos": pasos, "completos": completos, "total": len(pasos), "porcentaje": round(completos / len(pasos) * 100)}


def obtener_checklist_progreso(usuario_id, cuenta_id):
    """
    "Completá tu perfil" — pedido explícito, con barra de progreso. Nada de esto es una tabla nueva: se deriva de datos que ya existen.
    Todo se mide sobre la cuenta ACTIVA (un usuario con dos cuentas no suma los datos de las dos).
    """
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT onboarding_completo FROM usuarios WHERE id = %s", (usuario_id,))
        onboarding_completo = bool((cursor.fetchone() or [False])[0])

        cursor.execute("SELECT sincronizacion_inicial_completa, capacidades, flex_umbrales FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        cuenta = cursor.fetchone() or (False, None, None)

        cursor.execute("""
            SELECT COUNT(*) FILTER (WHERE estado = 'active'),
                   COUNT(*) FILTER (WHERE estado = 'active' AND COALESCE(precio_costo, 0) > 0)
            FROM productos_padre
        """)
        activas, con_costo = cursor.fetchone()

        cursor.execute("SELECT EXISTS(SELECT 1 FROM gastos_operativos), EXISTS(SELECT 1 FROM ventas)")
        tiene_gastos, tiene_ventas = cursor.fetchone()

    return armar_checklist(onboarding_completo, bool(cuenta[0]), activas or 0, con_costo or 0, tiene_gastos, tiene_ventas,
                           cuenta[1] if isinstance(cuenta[1], dict) else {}, cuenta[2])

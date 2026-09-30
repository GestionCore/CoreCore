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


def obtener_checklist_progreso(usuario_id, cuenta_id):
    """
    "Completá tu perfil" — pedido explícito, con barra de progreso. Los
    3 primeros pasos (encuesta de onboarding, conectar MeLi, primera
    sincronización) ya están resueltos si el usuario llegó hasta acá —
    login_requerido no deja pasar sin eso — así que el checklist arranca
    ya con algo de progreso en vez de en cero, y se enfoca en lo que
    realmente todavía puede faltar. Nada de esto es una tabla nueva: se
    deriva de datos que ya existen, para no pedir otra migración más.
    """
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT onboarding_completo FROM usuarios WHERE id = %s", (usuario_id,))
        onboarding_completo = bool((cursor.fetchone() or [False])[0])

        cursor.execute("SELECT sincronizacion_inicial_completa FROM cuentas_meli WHERE id = %s", (cuenta_id,))
        sync_completa = bool((cursor.fetchone() or [False])[0])

        cursor.execute("SELECT COUNT(*) FROM productos_padre WHERE estado = 'active' AND precio_costo IS NOT NULL AND precio_costo > 0")
        tiene_costos = (cursor.fetchone()[0] or 0) > 0

        cursor.execute("SELECT COUNT(*) FROM gastos_operativos")
        tiene_gastos = (cursor.fetchone()[0] or 0) > 0

        cursor.execute("SELECT COUNT(*) FROM ventas")
        tiene_ventas = (cursor.fetchone()[0] or 0) > 0

    pasos = [
        {"id": "onboarding", "texto": "Contanos cómo vendés (encuesta inicial)", "completo": onboarding_completo, "link": None},
        {"id": "sync", "texto": "Primera sincronización con Mercado Libre", "completo": sync_completa, "link": None},
        {"id": "costos", "texto": "Cargar el costo de fabricación de al menos un producto", "completo": tiene_costos, "link": "/costos"},
        {"id": "gastos", "texto": "Cargar tus gastos fijos (alquiler, bolsas, etc.)", "completo": tiene_gastos, "link": "/costos"},
        {"id": "ventas", "texto": "Tener al menos una venta sincronizada", "completo": tiene_ventas, "link": "/metricas"},
    ]
    completos = sum(1 for p in pasos if p["completo"])
    return {"pasos": pasos, "completos": completos, "total": len(pasos), "porcentaje": round(completos / len(pasos) * 100)}

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


def guardar_respuestas(usuario_id, prioridad, experiencia, pantalla):
    if prioridad not in OPCIONES_PRIORIDAD or experiencia not in OPCIONES_EXPERIENCIA or pantalla not in OPCIONES_PANTALLA:
        return False
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            UPDATE usuarios SET onboarding_completo = true, prioridad_principal = %s,
                                 experiencia_meli = %s, pantalla_preferida = %s
            WHERE id = %s
        """, (prioridad, experiencia, pantalla, usuario_id))
    return True


def obtener_endpoint_home(usuario_id):
    """A qué pantalla mandar a este usuario cuando entra — según lo que eligió en la encuesta."""
    with db.conexion_usuario(usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT pantalla_preferida FROM usuarios WHERE id = %s", (usuario_id,))
        fila = cursor.fetchone()
    pantalla = fila[0] if fila and fila[0] else "stock"
    return RUTA_POR_PANTALLA.get(pantalla, "landing")

"""
Asistente de Operaciones — el chat flotante que ya existía en el
frontend (base.html / global.js) pero nunca tuvo backend. Responde
preguntas en lenguaje natural sobre EL NEGOCIO (ventas de hoy,
rentabilidad reciente, talles/inventario) armando primero un snapshot
real de la base y pasándoselo a la IA como contexto — nunca deja que
la IA "adivine" un número de memoria. Es de solo lectura: no escribe
nada en la base bajo ningún flujo.
"""
import json
from datetime import timedelta
import db
import dashboard
import analisis_stock
import ia_asistente
from utils import hoy_argentina, limpiar_titulo_modelo

PROMPT_SISTEMA = """Sos el Asistente de Operaciones de CoreLux, una app de gestión para vendedores de Mercado Libre. Respondés preguntas del vendedor sobre SU negocio usando ÚNICAMENTE los datos reales de abajo — nunca inventás un número que no esté ahí.

Hoy es {fecha_hoy}. Datos actuales del negocio:
{contexto_json}

Reglas:
- Respondé en español, corto y directo (2-4 oraciones), como si le hablaras al dueño de un local, no a un programador.
- Si te piden porcentajes o comparaciones, calculalos solo con los números de arriba (por ejemplo, unidades de un modelo sobre "unidades_vendidas" del período); si no podés, no los estimes.
- Si preguntan algo que no está en los datos de arriba (un período que no tenés, un producto que no aparece), decilo con honestidad en vez de inventar un número.
- No dês consejos fiscales/legales con total seguridad — para eso existe la sección de Monotributo, que ya avisa que hay que confirmar con un contador.
- Si preguntan cómo hacer algo en la app (no un dato del negocio), orientalos a la sección correspondiente (Ganancia Real, Stock, Publicidad, Costos, etc.) en vez de inventar pasos que no existen."""

MAX_LARGO_PREGUNTA = 500


def _consolidar_por_modelo(filas, limite=8):
    """Top de modelos (los talles se suman en un solo modelo): [(título, unidades, facturado)] de más a menos facturado."""
    modelos = {}
    for titulo, unidades, facturado in filas:
        clave = limpiar_titulo_modelo(titulo) or (titulo or "Sin título")
        u, f = modelos.get(clave, (0, 0.0))
        modelos[clave] = (u + int(unidades or 0), f + float(facturado or 0))
    ordenados = sorted(modelos.items(), key=lambda kv: kv[1][1], reverse=True)[:limite]
    return [{"modelo": m, "unidades": u, "facturado": round(f, 2)} for m, (u, f) in ordenados]


def _mes_en_curso(usuario_id, cuenta_id):
    p = dashboard.obtener_proyeccion_mes(usuario_id, cuenta_id)
    if not p:
        return "sin ventas este mes ni el anterior"
    return {
        "mes": p["mes_nombre"], "dia_del_mes": p["dia"], "facturado_hasta_hoy": p["facturado_raw"], "unidades": p["unidades"],
        "proyeccion_al_cierre_al_ritmo_actual": p["proyectado_raw"], "mes_anterior_completo": p["mes_anterior_raw"],
        "mes_anterior_hasta_el_mismo_dia": p["mismo_punto"], "variacion_vs_mismo_punto_del_mes_anterior_pct": p["vs_mismo_punto"],
    }


def _armar_contexto(usuario_id, cuenta_id=None):
    hoy = hoy_argentina()
    desde_30d = hoy - timedelta(days=30)
    hoy_str = hoy.strftime("%Y-%m-%d")
    desde_30d = desde_30d.strftime("%Y-%m-%d")

    ventas_hoy = dashboard.obtener_ventas_hoy(usuario_id, cuenta_id)

    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(precio_venta*cantidad),0), COALESCE(SUM(cargo_venta),0),
                   COALESCE(SUM(costo_envio),0), COUNT(DISTINCT id_orden), COALESCE(SUM(cantidad),0)
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s AND origen = 'meli'
        """, (desde_30d, hoy_str))
        facturado_30d, comision_30d, envios_30d, ordenes_30d, unidades_30d = cursor.fetchone()

        cursor.execute("""
            SELECT fecha_venta, COALESCE(SUM(precio_venta*cantidad),0), COUNT(DISTINCT id_orden)
            FROM ventas WHERE fecha_venta BETWEEN %s AND %s AND origen = 'meli' GROUP BY fecha_venta ORDER BY fecha_venta
        """, (desde_30d, hoy_str))
        por_dia = [{"fecha": f.isoformat(), "facturado": round(float(t), 2), "ordenes": o} for f, t, o in cursor.fetchall()]

        cursor.execute("""
            SELECT titulo, SUM(cantidad), SUM(precio_venta*cantidad) FROM ventas
            WHERE fecha_venta BETWEEN %s AND %s AND origen = 'meli' GROUP BY titulo
        """, (desde_30d, hoy_str))
        top_modelos = _consolidar_por_modelo(cursor.fetchall())

        cursor.execute("SELECT COUNT(*), COALESCE(SUM(stock_propio),0), COALESCE(SUM(stock_full),0) FROM productos_variantes")
        variantes_totales, stock_propio_total, stock_full_total = cursor.fetchone()

        en_riesgo = analisis_stock.obtener_variantes_en_riesgo(cursor)

    try:
        mes = _mes_en_curso(usuario_id, cuenta_id)
    except Exception as e:
        print(f"[ChatIA] ⚠️ No se pudo armar el mes en curso: {e}")
        mes = "no disponible ahora"

    return {
        "ventas_de_hoy": {
            "facturado": ventas_hoy.get("facturado_hoy"), "ordenes": ventas_hoy.get("ordenes_hoy"),
            "unidades": ventas_hoy.get("unidades_hoy"),
        },
        "resumen_ultimos_30_dias": {
            "facturado": round(float(facturado_30d), 2), "ordenes_distintas": ordenes_30d, "unidades_vendidas": int(unidades_30d),
            "comisiones_meli": round(float(comision_30d), 2), "envios": round(float(envios_30d), 2),
            "nota": "Esto NO es la Ganancia Neta Real (falta publicidad y costo de fabricación) — para el número exacto, la sección Ganancia Real.",
        },
        "mes_en_curso": mes,
        "ventas_por_dia_ultimos_30_dias": por_dia,
        "modelos_mas_vendidos_ultimos_30_dias": top_modelos,
        "inventario": {
            "variantes_publicadas": variantes_totales,
            "stock_total_deposito_propio": stock_propio_total, "stock_total_full": stock_full_total,
            "variantes_en_riesgo_de_quiebre": [
                {"producto": v["titulo"], "variante": v["talle"], "stock_restante": v["stock_total"], "dias_restantes": v["dias_restantes"]}
                for v in en_riesgo[:8]
            ] if en_riesgo else "ninguno detectado ahora mismo",
        },
    }


def responder_pregunta(usuario_id, pregunta, cuenta_id=None):
    pregunta = (pregunta or "").strip()
    if not pregunta:
        return "Escribí una pregunta primero."
    if len(pregunta) > MAX_LARGO_PREGUNTA:
        return "Esa pregunta es demasiado larga — probá con algo más corto y directo."

    try:
        contexto = _armar_contexto(usuario_id, cuenta_id)
    except Exception as e:
        print(f"[ChatIA] ⚠️ Error armando el contexto: {e}")
        return "No pude leer los datos del negocio ahora mismo — probá de nuevo en un rato."

    prompt = PROMPT_SISTEMA.format(
        fecha_hoy=hoy_legible(), contexto_json=json.dumps(contexto, ensure_ascii=False, indent=2, default=str)
    )
    ok, respuesta = ia_asistente.preguntar_ia(prompt, pregunta, max_tokens=500, temperatura=0.3)
    if not ok:
        return f"No pude conectar con la IA ({respuesta})."
    return respuesta


def hoy_legible():
    return hoy_argentina().strftime("%Y-%m-%d")

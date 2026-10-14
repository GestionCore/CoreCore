"""
Panel de salud del sistema para el dueño (/admin/salud): de un vistazo, si la base responde, si cada cuenta se está sincronizando, qué
migraciones faltan, cuántas conexiones usa el proceso y qué configuración falta. Solo lectura; solo ADMIN_EMAIL.

Usa conexion_admin porque mira TODAS las cuentas (una de las excepciones documentadas, igual que /admin).
"""
import os
import time
from datetime import datetime, timezone

from flask import Blueprint, g, render_template

import config
import controles_de_datos
import db
from auditoria import ETIQUETAS
from auth.middleware import login_requerido, admin_requerido
from utils import ARGENTINA

bp = Blueprint("salud_sistema", __name__)

CICLO_SYNC_MINUTOS = 4
AVISO_DESPUES_DE = 3 * CICLO_SYNC_MINUTOS       # 12 min: se salteó algún ciclo
FALLA_DESPUES_DE = 30                           # 30 min sin sincronizar: algo está mal
HORA_LIMITE_RELEVAMIENTO = 6                    # el relevamiento diario de mercado arranca a las 4 (hora argentina): a las 6 ya tiene que haber corrido
MINUTOS_PARA_DARLO_POR_CORTADO = 30             # corre unos 4 minutos: si lleva media hora «en curso», se cortó
PROPORCION_DE_ERRORES_QUE_AVISA = 0.05          # más de 1 error cada 20 llamadas


def estado_de_cuenta(activa, tiene_tokens, sync_inicial, minutos_desde_sync):
    """(tono, texto) de una cuenta: danger = hay que actuar, warn = mirar, ok = al día."""
    if not activa:
        return "danger", "Desconectada: la persona tiene que volver a conectar su cuenta"
    if not tiene_tokens:
        return "danger", "Sin credenciales guardadas: tiene que volver a conectar"
    if not sync_inicial:
        return "warn", "Primera sincronización en curso"
    if minutos_desde_sync is None:
        return "warn", "Todavía no sincronizó ventas"
    if minutos_desde_sync > FALLA_DESPUES_DE:
        return "danger", f"Sin sincronizar hace {_duracion(minutos_desde_sync)}"
    if minutos_desde_sync > AVISO_DESPUES_DE:
        return "warn", f"Última sincronización hace {_duracion(minutos_desde_sync)}"
    return "ok", "Al día"


def estado_del_relevamiento(corridas, ahora_arg):
    """
    (tono, texto) del relevamiento diario de mercado (mercado_relevador.py) a partir de sus últimas corridas, la más nueva primero. Es la forma de enterarse de que Mercado Libre cerró un endpoint:
    una lista que de golpe no trae nada en ninguna categoría. `corridas`: dicts de mercado_relevamientos; `ahora_arg`: la hora de Argentina con zona horaria.
    """
    diarias = [c for c in corridas if c["tipo"] == "diario"]
    if not diarias:
        return "warn", "Todavía no corrió ningún relevamiento"
    ultima = diarias[0]
    detalle = ultima.get("detalle") or {}
    if ultima["fin"] is None:
        minutos = (ahora_arg - ultima["inicio"]).total_seconds() / 60
        if minutos > MINUTOS_PARA_DARLO_POR_CORTADO:
            return "danger", f"El relevamiento empezó hace {_duracion(minutos)} y no terminó: se cortó"
        return "ok", "Corriendo ahora"
    if ultima["fecha"] < ahora_arg.date() and ahora_arg.hour >= HORA_LIMITE_RELEVAMIENTO:
        return "danger", f"Hoy no corrió el relevamiento (el último fue el {ultima['fecha'].strftime('%d/%m')})"
    if not ultima["categorias"]:
        return "danger", "No pudo medir ninguna categoría: puede que Mercado Libre haya cerrado un endpoint"
    if detalle.get("con_tendencias") == 0:
        return "danger", "Ninguna categoría trajo búsquedas en alza: puede que Mercado Libre haya cerrado /trends"
    errores, llamadas = ultima["errores"] or 0, max(ultima["llamadas"] or 0, 1)
    if errores / llamadas > PROPORCION_DE_ERRORES_QUE_AVISA:
        return "warn", f"{errores} errores en {llamadas} llamadas: mirá el detalle abajo"
    return "ok", f"Al día: {ultima['categorias']} categorías, {ultima['llamadas']} llamadas, {errores} errores"


def _duracion(minutos):
    minutos = int(minutos)
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 60 * 48:
        return f"{minutos // 60} h"
    return f"{minutos // 1440} días"


def _migraciones_en_disco():
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
    return sorted(f for f in os.listdir(carpeta) if f.endswith(".sql"))


def migraciones_pendientes(en_disco, aplicadas):
    """Archivos de migrations/ cuya versión (el prefijo numérico: '0029') no figura en schema_migrations."""
    return [m for m in en_disco if m.split("_", 1)[0] not in aplicadas]


def _estadisticas_del_pool(pool):
    if pool is None:
        return None
    try:
        s = pool.get_stats()
        return {"en_uso": s.get("pool_size", 0) - s.get("pool_available", 0), "tamano": s.get("pool_size", 0), "maximo": s.get("pool_max", 0),
                "esperando": s.get("requests_waiting", 0)}
    except Exception:
        return None


def obtener_estado():
    ahora = datetime.now(timezone.utc)
    estado = {"ahora": ahora}

    t0 = time.perf_counter()
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT 1")
        estado["base_ms"] = round((time.perf_counter() - t0) * 1000)

        cursor.execute("""
            SELECT c.id, u.email, c.nickname, c.activa, c.sincronizacion_inicial_completa, c.ultima_sincronizacion, c.ultima_sincronizacion_ventas,
                   t.cuenta_id IS NOT NULL, t.expira_en, u.plan
            FROM cuentas_meli c JOIN usuarios u ON u.id = c.usuario_id LEFT JOIN meli_tokens t ON t.cuenta_id = c.id
            ORDER BY c.id
        """)
        cuentas = []
        for cid, email, nick, activa, sync_ini, ult_catalogo, ult_ventas, tokens, expira, plan in cursor.fetchall():
            minutos = (ahora - ult_ventas).total_seconds() / 60 if ult_ventas else None
            tono, texto = estado_de_cuenta(bool(activa), bool(tokens), bool(sync_ini), minutos)
            # Los datos de verdad de cada cuenta: lo que las pruebas (con datos armados a mano) no pueden ver. Si un control falla no se cae la página: se dice.
            try:
                hallazgos = controles_de_datos.evaluar(controles_de_datos.reunir(cursor, cid))
            except Exception as e:
                conexion.rollback()
                hallazgos = [{"clave": "controles", "tono": "warn", "titulo": "No se pudieron revisar los datos de esta cuenta", "detalle": f"{type(e).__name__}: {e}"[:200]}]
            cuentas.append({"id": cid, "email": email, "nickname": nick, "plan": plan, "tono": tono, "texto": texto,
                            "ultima_ventas": ult_ventas, "ultimo_catalogo": ult_catalogo, "hallazgos": hallazgos})
        estado["cuentas"] = cuentas

        cursor.execute("SELECT version FROM schema_migrations")
        aplicadas = {v for (v,) in cursor.fetchall()}
        disco = _migraciones_en_disco()
        estado["migraciones"] = {"aplicadas": len(aplicadas), "en_disco": len(disco),
                                 "pendientes": migraciones_pendientes(disco, aplicadas)}

        cursor.execute("SELECT tipo, fecha, inicio, fin, categorias, llamadas, errores, detalle FROM mercado_relevamientos ORDER BY id DESC LIMIT 14")
        corridas = [dict(zip(("tipo", "fecha", "inicio", "fin", "categorias", "llamadas", "errores", "detalle"), f)) for f in cursor.fetchall()]
        tono, texto = estado_del_relevamiento(corridas, datetime.now(ARGENTINA))
        estado["mercado"] = {"tono": tono, "texto": texto, "corridas": corridas}

        cursor.execute("SELECT accion, count(*) FROM auditoria WHERE creado_en > now() - interval '24 hours' GROUP BY accion ORDER BY 2 DESC")
        estado["actividad_24h"] = [(ETIQUETAS.get(a, a), n) for a, n in cursor.fetchall()]

    estado["pools"] = {"usuario": _estadisticas_del_pool(db._pool), "admin": _estadisticas_del_pool(db._pool_admin), "pool_max": db.POOL_MAX}

    import scheduler
    estado["scheduler"] = {"este_proceso": scheduler._scheduler_apscheduler is not None}

    faltan, recomendadas = config.validar()
    estado["config"] = {"faltan": faltan, "recomendadas": recomendadas}
    estado["servidor"] = {"app": os.getenv("FLY_APP_NAME") or "local", "region": os.getenv("FLY_REGION") or "—",
                          "maquina": os.getenv("FLY_MACHINE_ID") or "—", "version": (os.getenv("FLY_IMAGE_REF") or "—").rsplit(":", 1)[-1]}
    hallazgos = [h for c in cuentas for h in c["hallazgos"]]
    estado["problemas"] = (sum(1 for c in cuentas if c["tono"] == "danger") + len(estado["migraciones"]["pendientes"]) + len(faltan) + (estado["mercado"]["tono"] == "danger")
                           + sum(1 for h in hallazgos if h["tono"] == "danger"))
    estado["avisos"] = sum(1 for c in cuentas if c["tono"] == "warn") + len(recomendadas) + (estado["mercado"]["tono"] == "warn") + sum(1 for h in hallazgos if h["tono"] == "warn")
    return estado


@bp.route("/admin/salud")
@login_requerido
@admin_requerido
def admin_salud():
    return render_template("admin_salud.html", e=obtener_estado(), active_nav="admin", usuario=g.usuario_id)

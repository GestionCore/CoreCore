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
import db
from auditoria import ETIQUETAS
from auth.middleware import login_requerido, admin_requerido

bp = Blueprint("salud_sistema", __name__)

CICLO_SYNC_MINUTOS = 4
AVISO_DESPUES_DE = 3 * CICLO_SYNC_MINUTOS       # 12 min: se salteó algún ciclo
FALLA_DESPUES_DE = 30                           # 30 min sin sincronizar: algo está mal


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
            cuentas.append({"id": cid, "email": email, "nickname": nick, "plan": plan, "tono": tono, "texto": texto,
                            "ultima_ventas": ult_ventas, "ultimo_catalogo": ult_catalogo})
        estado["cuentas"] = cuentas

        cursor.execute("SELECT version FROM schema_migrations")
        aplicadas = {v for (v,) in cursor.fetchall()}
        disco = _migraciones_en_disco()
        estado["migraciones"] = {"aplicadas": len(aplicadas), "en_disco": len(disco),
                                 "pendientes": migraciones_pendientes(disco, aplicadas)}

        cursor.execute("SELECT accion, count(*) FROM auditoria WHERE creado_en > now() - interval '24 hours' GROUP BY accion ORDER BY 2 DESC")
        estado["actividad_24h"] = [(ETIQUETAS.get(a, a), n) for a, n in cursor.fetchall()]

    estado["pools"] = {"usuario": _estadisticas_del_pool(db._pool), "admin": _estadisticas_del_pool(db._pool_admin), "pool_max": db.POOL_MAX}

    import scheduler
    estado["scheduler"] = {"este_proceso": scheduler._scheduler_apscheduler is not None}

    faltan, recomendadas = config.validar()
    estado["config"] = {"faltan": faltan, "recomendadas": recomendadas}
    estado["servidor"] = {"app": os.getenv("FLY_APP_NAME") or "local", "region": os.getenv("FLY_REGION") or "—",
                          "maquina": os.getenv("FLY_MACHINE_ID") or "—", "version": (os.getenv("FLY_IMAGE_REF") or "—").rsplit(":", 1)[-1]}
    estado["problemas"] = sum(1 for c in cuentas if c["tono"] == "danger") + len(estado["migraciones"]["pendientes"]) + len(faltan)
    estado["avisos"] = sum(1 for c in cuentas if c["tono"] == "warn") + len(recomendadas)
    return estado


@bp.route("/admin/salud")
@login_requerido
@admin_requerido
def admin_salud():
    return render_template("admin_salud.html", e=obtener_estado(), active_nav="admin", usuario=g.usuario_id)

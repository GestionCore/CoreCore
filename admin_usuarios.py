"""Lo que muestra el panel /admin sobre los usuarios: cuánto le queda a cada prueba, quién entró esta semana y cómo se extiende una prueba."""

DIAS_POR_VENCER = 3          # una prueba que vence en este plazo se marca como "por vencer"
ACTIVO_EN_DIAS = 7           # "activo" = entró a CoreLux en los últimos 7 días


def dias_de_prueba(plan, trial_termina_en, ahora):
    """Días que le quedan a la prueba (0 = vence hoy, negativo = ya venció). None si no está en el plan trial o no tiene fecha de fin."""
    if plan != "trial" or not trial_termina_en or not hasattr(trial_termina_en, "strftime"):
        return None
    if trial_termina_en >= ahora:
        return (trial_termina_en - ahora).days
    return -((ahora - trial_termina_en).days + 1)


def armar_usuarios(filas, hoy, ahora):
    """
    Convierte las filas de la consulta de /admin en (usuarios, estadísticas). Cada fila:
    (id, email, nombre, plan, activo, creado_en, trial_termina_en, onboarding_completo, num_cuentas, ultima_sync, racha_dias, sync_completa, ultima_visita)
    """
    usuarios = []
    for f in filas:
        ultima_visita = f[12]
        usuarios.append({
            "id": f[0], "email": f[1], "nombre": f[2],
            "plan": f[3], "activo": f[4],
            "creado_en": f[5] if f[5] and hasattr(f[5], "strftime") else "",
            "trial_termina_en": f[6] if f[6] and hasattr(f[6], "strftime") else "",
            "dias_trial": dias_de_prueba(f[3], f[6], ahora),
            "onboarding_completo": bool(f[7]),
            "num_cuentas": int(f[8] or 0),
            "ultima_sync": f[9] if f[9] and hasattr(f[9], "strftime") else None,
            "racha_dias": int(f[10] or 0),
            "sync_completa": bool(f[11]),
            "ultima_visita": ultima_visita,
            "visito_en_7_dias": bool(ultima_visita and 0 <= (hoy - ultima_visita).days <= ACTIVO_EN_DIAS),
        })
    stats = {
        "total": len(usuarios),
        "trial": sum(1 for u in usuarios if u["plan"] == "trial"),
        "base": sum(1 for u in usuarios if u["plan"] == "base"),
        "elite": sum(1 for u in usuarios if u["plan"] == "elite"),
        "cancelado": sum(1 for u in usuarios if u["plan"] == "cancelado"),
        "inactivos": sum(1 for u in usuarios if not u["activo"]),
        "activos_7d": sum(1 for u in usuarios if u["visito_en_7_dias"]),
        "por_vencer": sum(1 for u in usuarios if u["dias_trial"] is not None and 0 <= u["dias_trial"] <= DIAS_POR_VENCER),
        "vencidas": sum(1 for u in usuarios if u["dias_trial"] is not None and u["dias_trial"] < 0),
    }
    return usuarios, stats


def extender_prueba(cursor, usuario_id, dias):
    """Suma `dias` a la prueba: desde hoy si ya venció, desde su fecha de fin si todavía no. Solo al plan trial. Devuelve la nueva fecha de fin o None."""
    cursor.execute(
        """UPDATE usuarios
           SET trial_termina_en = GREATEST(COALESCE(trial_termina_en, now()), now()) + make_interval(days => %s), actualizado_en = now()
           WHERE id = %s AND plan = 'trial'
           RETURNING trial_termina_en""",
        (dias, usuario_id),
    )
    fila = cursor.fetchone()
    return fila[0] if fila else None

"""
Reactivar publicaciones pausadas que ya tienen stock.

Cuando una publicación se queda sin stock, Mercado Libre la pausa sola; al reponer, hay que volver a activarla a mano y es fácil que
se olvide: plata que no se cobra. Acá se listan las pausadas que SÍ se pueden reactivar (pausadas a mano o por falta de stock, no las
bloqueadas por moderación) y que tienen unidades, y se reactivan solo las que la persona confirma.

Todo se vuelve a validar en el servidor: el pedido trae ids, nunca se confía en que sigan pausadas ni en que sean reactivables.
"""
import meli_http

MAXIMO_POR_PEDIDO = 50
SUB_ESTADOS_REACTIVABLES = {"out_of_stock", "paused_by_seller"}       # y vacío; el resto (suspended, under_review…) es de Mercado Libre
URL_ITEM = "https://api.mercadolibre.com/items/{}"


def puede_reactivarse(sub_estado):
    """
    True si el motivo de la pausa permite reactivar desde acá: pausada por el vendedor y/o por falta de stock (o sin motivo).
    None = todavía no se conoce el motivo (primera sincronización después de la migración): no se ofrece hasta saberlo.
    """
    if sub_estado is None:
        return False
    return {s for s in sub_estado.split(",") if s} <= SUB_ESTADOS_REACTIVABLES


def motivo_legible(sub_estado):
    sub_estado = sub_estado or ""
    if "paused_by_seller" in sub_estado:
        return "Pausada por vos"
    return "Se pausó por falta de stock" if "out_of_stock" in sub_estado else "Pausada"


def listar(cursor):
    """Publicaciones pausadas, reactivables y con stock (propio + FULL), las de más stock primero."""
    cursor.execute("""
        SELECT p.id_meli, p.titulo, p.thumbnail, p.precio, p.permalink, p.sub_estado,
               COALESCE(SUM(COALESCE(v.stock_propio, 0) + COALESCE(v.stock_full, 0)), 0) AS stock
        FROM productos_padre p
        LEFT JOIN productos_variantes v ON v.id_padre = p.id
        WHERE p.estado = 'paused'
        GROUP BY p.id
        HAVING COALESCE(SUM(COALESCE(v.stock_propio, 0) + COALESCE(v.stock_full, 0)), 0) > 0
        ORDER BY stock DESC, p.titulo
    """)
    return [{"id_meli": i, "titulo": t, "thumbnail": th, "precio": float(pr) if pr is not None else None, "permalink": pl,
             "stock": int(st), "motivo": motivo_legible(sub)}
            for i, t, th, pr, pl, sub, st in cursor.fetchall() if puede_reactivarse(sub)]


def _mensaje_de_error(respuesta):
    try:
        cuerpo = respuesta.json()
        return str(cuerpo.get("message") or cuerpo.get("error") or respuesta.status_code)[:160]
    except Exception:
        return f"Mercado Libre respondió {respuesta.status_code}"


def reactivar(cursor, cuenta_id, access_token, ids):
    """
    Reactiva las publicaciones pedidas que sigan siendo reactivables. Devuelve una lista de {"id", "ok", "detalle"} (una por id pedido).
    Una que falle no corta a las demás; las que Mercado Libre acepta pasan a 'active' también en la base, sin esperar al próximo sync.
    """
    ids = list(dict.fromkeys(str(i) for i in (ids or [])))[:MAXIMO_POR_PEDIDO]
    candidatas = {c["id_meli"] for c in listar(cursor)}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resultados = []
    for id_meli in ids:
        if id_meli not in candidatas:
            resultados.append({"id": id_meli, "ok": False, "detalle": "Ya no está pausada o no se puede reactivar desde acá"})
            continue
        try:
            r = meli_http.put(URL_ITEM.format(id_meli), headers=headers, json={"status": "active"})
        except Exception as e:
            resultados.append({"id": id_meli, "ok": False, "detalle": f"No se pudo conectar con Mercado Libre: {e}"[:160]})
            continue
        if r.status_code in (200, 201):
            cursor.execute("UPDATE productos_padre SET estado = 'active', sub_estado = '' WHERE cuenta_id = %s AND id_meli = %s", (cuenta_id, id_meli))
            resultados.append({"id": id_meli, "ok": True, "detalle": "Reactivada"})
        else:
            resultados.append({"id": id_meli, "ok": False, "detalle": _mensaje_de_error(r)})
    return resultados

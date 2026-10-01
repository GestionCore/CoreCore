"""
Qué usa cada cuenta de Mercado Libre.

CoreLux lo usan vendedores de cualquier rubro: a quien no vende por FULL no le sirve ver stock de FULL, a quien no tiene
publicaciones de catálogo no le sirve la competencia de catálogo, a quien no hace publicidad no le sirve esa pantalla. Acá se
detecta qué aplica a cada cuenta (cuentas_meli.capacidades) y las pantallas esconden lo que no.

Cada capacidad es True / False / ausente. Ausente significa "todavía no se pudo saber" y NUNCA esconde nada: solo un False
confirmado lo hace. Un error de la API no cambia el valor anterior.
"""
import json
import meli_http

SITE_ID = "MLA"
DIAS_VIGENCIA = 3


def _ads(access_token):
    try:
        resp = meli_http.get("https://api.mercadolibre.com/advertising/advertisers?product_id=PADS",
                             headers={"Authorization": f"Bearer {access_token}", "Api-Version": "1"}, timeout=10)
    except Exception:
        return None
    if resp.status_code == 200:
        return any(a.get("site_id") == SITE_ID for a in (resp.json().get("advertisers") or []))
    if resp.status_code in (403, 404):
        return False
    return None


def _flex(access_token, seller_id):
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/flex/sites/{SITE_ID}/users/{seller_id}/subscriptions/v1",
                             headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    except Exception:
        return None
    if resp.status_code == 200:
        return any(s.get("mode") == "FLEX" and s.get("status") == "in" for s in (resp.json() or []))
    if resp.status_code == 404:
        return False
    return None


def detectar(cursor, cuenta_id, access_token, seller_id, previas=None):
    """Capacidades de la cuenta. Lo que no se pudo confirmar conserva su valor anterior (o queda ausente)."""
    caps = dict(previas or {})

    for clave, valor in (("ads", _ads(access_token)), ("flex", _flex(access_token, seller_id))):
        if valor is not None:
            caps[clave] = valor

    # Lo que dicen las propias ventas y publicaciones pesa más que cualquier consulta: si hay ventas Flex, hay Flex.
    cursor.execute("""
        SELECT EXISTS(SELECT 1 FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND tipo_logistica = 'self_service'),
               EXISTS(SELECT 1 FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND tipo_logistica = 'fulfillment')
                 OR EXISTS(SELECT 1 FROM productos_padre WHERE cuenta_id = %(c)s AND tipo_logistica = 'fulfillment'),
               COUNT(*) FILTER (WHERE catalog_product_id IS NOT NULL),
               COUNT(*) FILTER (WHERE permalink IS NOT NULL)
        FROM productos_padre WHERE cuenta_id = %(c)s
    """, {"c": cuenta_id})
    hay_ventas_flex, hay_full, publicaciones_catalogo, publicaciones_sincronizadas = cursor.fetchone()
    if hay_ventas_flex:
        caps["flex"] = True
    caps["full"] = bool(hay_full)
    if publicaciones_catalogo:
        caps["catalogo"] = True
    elif publicaciones_sincronizadas:
        caps["catalogo"] = False   # el catálogo ya se sincronizó con los campos nuevos y ninguna publicación es de catálogo
    return caps


def guardar(cursor, cuenta_id, caps):
    cursor.execute("UPDATE cuentas_meli SET capacidades = %s::jsonb, capacidades_en = now() WHERE id = %s", (json.dumps(caps), cuenta_id))


def refrescar_si_hace_falta(cursor, cuenta_id, access_token, seller_id):
    """Detecta y guarda las capacidades si nunca se hizo o ya pasaron DIAS_VIGENCIA días. Devuelve el dict vigente."""
    cursor.execute("SELECT capacidades, capacidades_en IS NULL OR capacidades_en < now() - make_interval(days => %s) FROM cuentas_meli WHERE id = %s",
                   (DIAS_VIGENCIA, cuenta_id))
    fila = cursor.fetchone()
    previas, vencidas = (fila[0] or {}) if fila else {}, (fila[1] if fila else True)
    if not vencidas:
        return previas
    caps = detectar(cursor, cuenta_id, access_token, seller_id, previas)
    guardar(cursor, cuenta_id, caps)
    return caps


def visible(capacidades, requiere):
    """¿Se muestra algo que requiere esta capacidad? Solo un False confirmado lo esconde."""
    return not requiere or (capacidades or {}).get(requiere) is not False

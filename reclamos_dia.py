"""
Reclamos y devoluciones abiertos, para la parte «Reclamos» de Día a día.

Hasta ahora solo se veían como números sueltos («2 reclamos», «1 devolución»): no decían cuál era, por qué, si afectaba la reputación ni qué hacer. Acá cada uno es una tarjeta
con el producto, el motivo que informa Mercado Libre, desde cuándo está abierto, si afecta tu reputación, la plata retenida y UNA frase de qué hacer. Los reclamos se resuelven
en Mercado Libre (CoreLux no los responde por la persona): lo que hace esta parte es decir cuál mirar primero y llevarla directo a esa venta.

Nada de esto inventa datos: lo que Mercado Libre no informó se dice («todavía no informó…»), no se supone.
"""
from utils import formatear_estado_incidencia, formatear_moneda, hoy_argentina, plural

URL_VENTA = "https://www.mercadolibre.com.ar/ventas/{}/detalle"

TIPOS = {"claim": "Reclamo", "return": "Devolución o cambio", "cancelacion": "Cancelación"}

SQL_ABIERTOS = """
    SELECT i.id_reclamo, i.id_orden, i.tipo, i.motivo, i.estado, i.monto_retenido, i.fecha, i.afecta_reputacion,
           (SELECT MIN(v.titulo) FROM ventas v WHERE v.cuenta_id = i.cuenta_id AND v.id_orden = i.id_orden) AS titulo
    FROM incidencias_posventa i
    WHERE i.cuenta_id = %s AND i.estado NOT IN ('closed', 'resolved')
    ORDER BY i.fecha
"""


def listar_abiertos(cursor, cuenta_id):
    cursor.execute(SQL_ABIERTOS, (cuenta_id,))
    columnas = ("id_reclamo", "id_orden", "tipo", "motivo", "estado", "monto_retenido", "fecha", "afecta_reputacion", "titulo")
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def _impacto(tipo, afecta):
    """(texto, tono) de si cuenta contra la reputación. Solo un RECLAMO puede afectarla (devoluciones, cambios y cancelaciones no, por sí solos)."""
    if tipo != "claim":
        return "No afecta tu reputación por sí sola", "neutral"
    if afecta == "affected":
        return "Afecta tu reputación", "danger"
    if afecta == "not_affected":
        return "No afecta tu reputación", "neutral"
    return "Mercado Libre todavía no informó si afecta tu reputación", "warn"


def _que_hacer(tipo, estado, afecta):
    estado = (estado or "").lower()
    if tipo == "claim" and estado in ("mediation", "dispute"):
        return "Mercado Libre está mediando. Entrá al reclamo y respondé o cargá lo que te pidan."
    if tipo == "claim":
        if afecta == "not_affected":
            return "El comprador abrió un reclamo que no afecta tu reputación. Igual conviene resolverlo con él desde Mercado Libre para que no pase a mediación."
        return "El comprador abrió un reclamo. Resolverlo cuanto antes, desde Mercado Libre, es lo que mejor protege tu reputación."
    if tipo == "return":
        return "El comprador devuelve el producto o pidió un cambio. Seguí el estado desde Mercado Libre y, cuando te llegue, revisalo y confirmalo ahí."
    return "La venta se está cancelando. No tenés que hacer nada."


def _estado_texto(estado, en_mediacion):
    """«En mediación con Mercado Libre» o «Abierto»: la etapa interna 'claim' ya no se lee como «Reclamo activo» en una devolución."""
    if en_mediacion:
        return "En mediación con Mercado Libre"
    if (estado or "").lower() in ("claim", "opened", "open", ""):
        return "Abierto"
    return formatear_estado_incidencia(estado)


def _desde(fecha, hoy):
    if not fecha:
        return None, None
    dias = max(0, (hoy - (fecha.date() if hasattr(fecha, "date") else fecha)).days)
    return dias, ("hoy" if dias == 0 else ("ayer" if dias == 1 else f"hace {dias} días"))


def armar(filas, hoy=None):
    """Las tarjetas, con lo más urgente primero: reclamos que afectan la reputación (los que Mercado Libre ya está mediando, antes), después el resto, y a igual urgencia el más viejo."""
    hoy = hoy or hoy_argentina()
    tarjetas = []
    for f in filas:
        tipo = f["tipo"] if f["tipo"] in TIPOS else "claim"
        impacto, tono = _impacto(tipo, f["afecta_reputacion"])
        dias, desde = _desde(f["fecha"], hoy)
        en_mediacion = (f["estado"] or "").lower() in ("mediation", "dispute")
        retenido = float(f["monto_retenido"] or 0)
        # 0 = afecta (o no se sabe) y en mediación · 1 = afecta · 2 = en mediación sin impacto · 3 = otro reclamo · 4 = devolución o cambio · 5 = cancelación (no hay nada que hacer)
        urgencia = (0 if (tono in ("danger", "warn") and en_mediacion) else (1 if tono in ("danger", "warn") else (2 if en_mediacion else {"claim": 3, "return": 4}.get(tipo, 5))))
        tarjetas.append({
            "id": f["id_reclamo"], "tipo": tipo, "tipo_texto": TIPOS[tipo],
            "titulo": f["titulo"] or (f"Venta {f['id_orden']}" if f["id_orden"] else "Venta sin detalle"),
            "motivo": f["motivo"] or "Mercado Libre no informó el motivo",
            "estado_texto": _estado_texto(f["estado"], en_mediacion), "en_mediacion": en_mediacion,
            "impacto": impacto, "tono": "danger" if tono == "danger" else ("warn" if tono == "warn" or en_mediacion else "neutral"),
            "dias": dias, "desde": desde,
            "retenido": retenido, "retenido_texto": formatear_moneda(retenido) if retenido > 0 else None,
            "que_hacer": _que_hacer(tipo, f["estado"], f["afecta_reputacion"]),
            "link": URL_VENTA.format(f["id_orden"]) if f["id_orden"] else None,
            "_orden": (urgencia, -(dias or 0)),
        })
    tarjetas.sort(key=lambda t: t["_orden"])
    for t in tarjetas:
        del t["_orden"]
    return tarjetas


def resumen(tarjetas):
    """Los tres números de arriba y la frase que los resume."""
    abiertos = len(tarjetas)
    afectan = sum(1 for t in tarjetas if t["tono"] == "danger" or (t["tipo"] == "claim" and "todavía no informó" in t["impacto"]))
    retenido = round(sum(t["retenido"] for t in tarjetas), 2)
    if not abiertos:
        frase = "No tenés reclamos ni devoluciones abiertos."
    elif afectan:
        frase = f"{plural(afectan, 'reclamo')} {'puede afectar' if afectan == 1 else 'pueden afectar'} tu reputación: empezá por {'ese' if afectan == 1 else 'los de arriba'}."
    else:
        frase = f"Tenés {plural(abiertos, 'caso abierto', 'casos abiertos')}, ninguno afecta tu reputación."
    return {"abiertos": abiertos, "afectan": afectan, "retenido": retenido, "retenido_texto": formatear_moneda(retenido), "frase": frase}

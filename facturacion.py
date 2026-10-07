"""
Facturación — portado de Santi Mens.

Mismo tipo de bug que encontré en ads.py: `_cache_periodos` era un
ÚNICO slot global (ni siquiera por cuenta), y `_cache_resumenes` cacheaba
por período (ej: "2026-09") sin cuenta_id — dos cuentas consultando el
mismo mes se hubieran pisado los resúmenes de facturación entre sí.
Ambas cachés ahora incluyen cuenta_id en su clave.
"""
import time
import meli_http
from utils import formatear_moneda

BASE_URL = "https://api.mercadolibre.com/billing/integration"

_cache_periodos = {}
_cache_resumenes = {}
TTL_SEGUNDOS = 600  # 10 minutos


def obtener_periodos(access_token, cuenta_id, group="ML"):
    ahora = time.time()
    cacheado = _cache_periodos.get(cuenta_id)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"{BASE_URL}/monthly/periods", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            resultado = data if isinstance(data, list) else data.get("results", [])
            _cache_periodos[cuenta_id] = {"data": resultado, "timestamp": ahora}
            return resultado
        print(f"[Facturación] ⚠️ No se pudieron traer los períodos: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        print(f"[Facturación] ❌ Error de conexión: {e}")

    return cacheado["data"] if cacheado else []


def obtener_resumen_periodo(access_token, cuenta_id, key, group="ML"):
    ahora = time.time()
    clave = (cuenta_id, group, key)
    cacheado = _cache_resumenes.get(clave)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"{BASE_URL}/periods/key/{key}/summary/details", headers=headers, params={"group": group, "document_type": "BILL"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            _cache_resumenes[clave] = {"data": data, "timestamp": ahora}
            return data
        print(f"[Facturación] ⚠️ No se pudo traer el resumen del período {key}: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        print(f"[Facturación] ❌ Error de conexión: {e}")

    return cacheado["data"] if cacheado else None


_cache_almacenamiento = {}


def obtener_costo_almacenamiento_full(access_token, cuenta_id, period_key, group="ML"):
    """
    Busca cargos de almacenamiento prolongado en FULL dentro del detalle de
    conciliación de un período mensual. MeLi no documenta un código de
    cargo estable para esto, así que buscamos por el texto legible del
    cargo (transaction_detail) — si no encuentra nada, no significa
    necesariamente que no haya cargo, conviene confirmar con un período
    real que sepas que tuvo este cargo.

    Cacheado 10 min por cuenta — antes se pedía sin caché en cada carga
    de /metricas (vía comparador_logistica), sumando una llamada extra
    a la API en cada visita a la página aunque el período no hubiera
    cambiado. cuenta_id va en la clave del caché a propósito: la misma
    familia de bug que ya se corrigió en ads.py y acá mismo (arriba,
    _cache_periodos/_cache_resumenes) — sin cuenta_id, dos cuentas
    consultando el mismo period_key se pisarían el resultado.
    """
    ahora = time.time()
    clave = (cuenta_id, group, period_key)
    cacheado = _cache_almacenamiento.get(clave)
    if cacheado and (ahora - cacheado["timestamp"]) < TTL_SEGUNDOS:
        return cacheado["data"]

    # El resumen de la factura (ya cacheado) trae cada cargo con su código: "CFWA" = "Cargo por servicio de almacenamiento Full".
    # El detalle por transacción (/details) sirve para otra cosa y tiene un límite de pedidos muy bajo (429 al paginar).
    CODIGOS_ALMACENAMIENTO = {"CFWA"}
    palabras_clave = ["almacenamiento", "storage", "stock antiguo", "bodega"]
    resumen = obtener_resumen_periodo(access_token, cuenta_id, period_key, group)
    if not resumen:
        return cacheado["data"] if cacheado else (None, 0)
    total, cantidad = 0.0, 0
    for cargo in (resumen.get("bill_includes") or {}).get("charges", []):
        etiqueta = (cargo.get("label") or "").lower()
        if cargo.get("type") in CODIGOS_ALMACENAMIENTO or any(p in etiqueta for p in palabras_clave):
            total += float(cargo.get("amount") or 0)
            cantidad += 1
    resultado = (round(total, 2), cantidad)
    _cache_almacenamiento[clave] = {"data": resultado, "timestamp": ahora}
    return resultado


# ── Cargos de la factura que NO están en lo que cuesta cada venta ─────────────────────────────────────────────────────────────────────────────
# Ganancia Real arma cada venta con su comisión, su envío y su publicidad. Hay cargos que Mercado Libre factura aparte, por mes, y que igual son plata
# que sale del negocio (a los vendedores se les acredita la diferencia): se descuentan de la ganancia repartidos por día (ver cargos_fuera_de_ventas).
#   CESM mantenimiento de la tienda oficial (eShop) · CSTP cargo de reputación · CFWA almacenamiento en FULL · CFRS retiro o descarte de stock en FULL
#   CDSD cargo por devolución (se descuenta lo que Mercado Libre anula después con BDSD: queda el neto)
CARGOS_FUERA_DE_VENTAS = {"CESM", "CSTP", "CFWA", "CFRS"}
CARGO_DEVOLUCION, ANULACION_DEVOLUCION = "CDSD", "BDSD"
ROTULOS_FUERA_DE_VENTAS = {
    "CESM": "Mantenimiento de eShop", "CSTP": "Cargo de reputación", "CFWA": "Almacenamiento en FULL", "CFRS": "Retiro o descarte de stock en FULL",
    CARGO_DEVOLUCION: "Cargos por devolución",
}


def fijos_de_resumen(resumen):
    """
    {código: {"label", "monto"}} de los cargos de una factura que no están en cada venta, con las devoluciones ya netas de su anulación. Solo los que tienen
    monto. `resumen` es la respuesta de /periods/key/{key}/summary/details.
    """
    bill = (resumen or {}).get("bill_includes") or {}
    fijos = {}
    for c in bill.get("charges", []):
        codigo = c.get("type")
        if codigo in CARGOS_FUERA_DE_VENTAS:
            etiqueta = ROTULOS_FUERA_DE_VENTAS.get(codigo) or c.get("label") or codigo
            fijos[codigo] = {"label": etiqueta, "monto": round(fijos.get(codigo, {}).get("monto", 0.0) + float(c.get("amount") or 0), 2)}
    devolucion = sum(float(c.get("amount") or 0) for c in bill.get("charges", []) if c.get("type") == CARGO_DEVOLUCION)
    anulado = sum(abs(float(b.get("amount") or 0)) for b in bill.get("bonuses", []) if b.get("type") == ANULACION_DEVOLUCION)
    neto = round(max(devolucion - anulado, 0.0), 2)
    if neto > 0:
        fijos[CARGO_DEVOLUCION] = {"label": ROTULOS_FUERA_DE_VENTAS[CARGO_DEVOLUCION], "monto": neto}
    return {k: v for k, v in fijos.items() if v["monto"]}


def _como_fecha(valor):
    from datetime import date
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def factor_de_reparto(periodo_desde, periodo_hasta, abierto, desde, hasta, hoy):
    """
    Qué parte de lo facturado en un período de facturación le toca al rango [desde, hasta]: los días que se superponen sobre los días del período.
    Un período abierto todavía no juntó todos sus días: se reparte entre los transcurridos hasta hoy.
    """
    p_desde, p_hasta, d, h, hoy = _como_fecha(periodo_desde), _como_fecha(periodo_hasta), _como_fecha(desde), _como_fecha(hasta), _como_fecha(hoy)
    fin_efectivo = min(p_hasta, hoy) if abierto else p_hasta
    dias_periodo = (fin_efectivo - p_desde).days + 1
    if dias_periodo <= 0:
        return 0.0
    solape = (min(h, fin_efectivo) - max(d, p_desde)).days + 1
    return max(solape, 0) / dias_periodo


def repartir_fijos(fijos_por_periodo, desde, hasta, hoy):
    """
    Suma, para el rango [desde, hasta], la parte de los cargos fijos que le corresponde de cada período. `fijos_por_periodo` es una lista de
    {"desde", "hasta", "abierto", "fijos": fijos_de_resumen(...)}. Devuelve {"total", "items": [{"label", "monto"}]} (mayores primero).
    """
    por_rotulo = {}
    for p in fijos_por_periodo:
        f = factor_de_reparto(p["desde"], p["hasta"], p["abierto"], desde, hasta, hoy)
        if f <= 0:
            continue
        for fijo in p["fijos"].values():
            por_rotulo[fijo["label"]] = por_rotulo.get(fijo["label"], 0.0) + fijo["monto"] * f
    items = sorted(({"label": k, "monto": round(v, 2)} for k, v in por_rotulo.items() if round(v, 2)), key=lambda i: -i["monto"])
    return {"total": round(sum(i["monto"] for i in items), 2), "items": items}


MAX_PERIODOS_NUEVOS_POR_CARGA = 6
TTL_PERIODO_CERRADO = 90 * 24 * 3600      # una factura cerrada no cambia
TTL_PERIODO_ABIERTO = 30 * 60


def cargos_fuera_de_ventas(usuario_id, cuenta_id, access_token, desde, hasta, hoy=None):
    """
    Los cargos mensuales de Mercado Libre que no están en cada venta (eShop, almacenamiento y retiros de FULL, reputación, devoluciones), repartidos por
    día sobre [desde, hasta]. Lo que se sabe de cada factura se guarda en la caché compartida (una cerrada no vuelve a pedirse; la abierta, cada 30 min) y
    si Mercado Libre no responde se usa lo último guardado. {"total", "items", "completo"}: `completo` es False si faltó traer algún período.
    """
    import cache_db
    import db
    from utils import hoy_argentina
    hoy = hoy or hoy_argentina()
    vacio = {"total": 0.0, "items": [], "completo": True}
    if not access_token:
        return {**vacio, "completo": False}
    periodos = obtener_periodos(access_token, cuenta_id)
    if not periodos:
        return {**vacio, "completo": False}
    d, h = _como_fecha(desde), _como_fecha(hasta)
    pendientes = []
    for p in periodos:
        rango = p.get("period") or {}
        if not (p.get("key") and rango.get("date_from") and rango.get("date_to")):
            continue
        if _como_fecha(rango["date_to"]) < d or _como_fecha(rango["date_from"]) > h:
            continue
        pendientes.append((p, rango))

    fijos_por_periodo, completo, nuevos = [], True, 0
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        for p, rango in pendientes:
            abierto = p.get("period_status") == "OPEN"
            clave, firma = f"factura_fijos:{p['key']}", "abierto" if abierto else "cerrado"
            hit, fijos = cache_db.leer(cursor, cuenta_id, clave, firma, ttl_segundos=TTL_PERIODO_ABIERTO if abierto else TTL_PERIODO_CERRADO)
            if not hit:
                if nuevos >= MAX_PERIODOS_NUEVOS_POR_CARGA:
                    completo = False
                    continue
                nuevos += 1
                resumen = obtener_resumen_periodo(access_token, cuenta_id, p["key"])
                if resumen and isinstance(resumen, dict):
                    fijos = fijos_de_resumen(resumen)
                    cache_db.guardar(cursor, cuenta_id, clave, fijos, firma)
                else:
                    # Mercado Libre no respondió: lo último que se guardó (aunque ya venciera) es mejor que no descontar nada
                    cursor.execute("SELECT valor FROM cache_valores WHERE cuenta_id = %s AND clave = %s", (cuenta_id, clave))
                    viejo = cursor.fetchone()
                    fijos = ((viejo[0] or {}).get("v") if viejo else None)
                    if fijos is None:
                        completo = False
                        continue
            fijos_por_periodo.append({"desde": rango["date_from"], "hasta": rango["date_to"], "abierto": abierto, "fijos": fijos})
    reparto = repartir_fijos(fijos_por_periodo, desde, hasta, hoy)
    return {**reparto, "completo": completo}


# ── La factura agrupada para mostrarla ─────────────────────────────────────────────────────────────────────────────────────────────────────────
GRUPOS = {
    "ventas": "Cargos por venta", "envios": "Cargos por envíos", "publicidad": "Publicidad", "full": "Servicios de FULL (almacenamiento y retiros)",
    "otros": "Otros cargos de Mercado Libre", "impuestos": "Impuestos y percepciones", "bonificaciones": "Bonificaciones",
}
TIPOS_ENVIO = {"CFF", "CDS", CARGO_DEVOLUCION}                      # Mercado Envíos (FULL y correo) y cargo por devolución
TIPOS_FULL = {"CFWA", "CFRS"}                                       # servicios de FULL: Mercado Libre los lista bajo «Cargos de envíos full», pero no son envíos
TIPOS_OTROS = {"CESM", "CSTP"}
ROTULOS_SIN_NOMBRE = {"CSTP": "Cargo de reputación", "BVFV": "Bonificación de cargos por venta", "BVFN": "Bonificación de cargos por venta", "CVFV": "Cargos por venta", "CVFN": "Cargos por venta",
                      "CVFF": "Cargos por venta"}
NOMBRE_FLEX = "Envíos Flex (tu propia logística)"


def grupo_de_cargo(tipo, grupo_meli=""):
    """A qué grupo de GRUPOS va un cargo. Se decide por el código: el grupo que informa Mercado Libre confunde (llama «de envíos full» al almacenamiento)."""
    g = (grupo_meli or "").strip().lower()
    if tipo and tipo.startswith("CV"):
        return "ventas"
    if tipo in TIPOS_ENVIO:
        return "envios"
    if tipo in TIPOS_FULL:
        return "full"
    if tipo == "PADS" or "public" in g:
        return "publicidad"
    if tipo in TIPOS_OTROS:
        return "otros"
    if "impuesto" in g or "percepci" in g:
        return "impuestos"
    if "full" in g:
        return "full"
    if "venta" in g:
        return "ventas"
    if "env" in g:
        return "envios"
    return "otros"


def agrupar_factura(resumen, flex_neto=0.0, flex_reintegro=0.0):
    """
    La factura de un período lista para mostrar: [{clave, label, monto, detalle: [{label, monto, nota}]}] y totales.
    `flex_neto` es lo que cuestan los envíos Flex de tu propia logística, ya descontado el reintegro de Mercado Libre; `flex_reintegro` el porcentaje (0,10).
    Flex NO está en la factura de Mercado Libre: entra en «Cargos por envíos» como una línea aparte y su reintegro en «Bonificaciones», así la suma
    es lo que de verdad te cuestan los envíos. Devuelve también `total_factura` (lo que dice Mercado Libre, sin Flex) y `total` (con Flex).
    """
    bill = (resumen or {}).get("bill_includes") or {}
    grupos = {clave: {"clave": clave, "label": etiqueta, "monto": 0.0, "lineas": {}} for clave, etiqueta in GRUPOS.items()}

    def sumar(clave, tipo, etiqueta, monto):
        g = grupos[clave]
        g["monto"] += monto
        nombre = (etiqueta if etiqueta and etiqueta != tipo else None) or ROTULOS_SIN_NOMBRE.get(tipo) or etiqueta or tipo or "Otros"
        g["lineas"][nombre] = g["lineas"].get(nombre, 0.0) + monto

    for c in bill.get("charges", []):
        sumar(grupo_de_cargo(c.get("type"), c.get("group_description")), c.get("type"), c.get("label"), float(c.get("amount") or 0))
    for b in bill.get("bonuses", []):
        sumar("bonificaciones", b.get("type"), b.get("label"), float(b.get("amount") or 0))
    total_factura = round(sum(g["monto"] for g in grupos.values()), 2)

    if flex_neto and flex_neto > 0:
        bruto = flex_neto / (1 - flex_reintegro) if 0 <= flex_reintegro < 1 else flex_neto
        grupos["envios"]["monto"] += bruto
        grupos["envios"]["lineas"][NOMBRE_FLEX] = grupos["envios"]["lineas"].get(NOMBRE_FLEX, 0.0) + bruto
        reintegro = bruto - flex_neto
        if reintegro > 0:
            grupos["bonificaciones"]["monto"] -= reintegro
            grupos["bonificaciones"]["lineas"][f"Reintegro de Mercado Libre por envíos Flex ({round(flex_reintegro * 100)}%)"] = -reintegro

    filas = []
    for g in grupos.values():
        if not g["lineas"]:
            continue
        detalle = []
        for nombre, monto in sorted(g["lineas"].items(), key=lambda x: -abs(x[1])):
            nota = None
            if nombre == NOMBRE_FLEX:
                nota = "lo cobra tu logística: no figura en la factura de Mercado Libre"
            elif nombre.startswith("Reintegro de Mercado Libre por envíos Flex"):
                nota = "calculado con tu configuración de Flex"
            detalle.append({"label": nombre, "monto": round(monto, 2), "nota": nota})
        filas.append({"clave": g["clave"], "label": g["label"], "monto": round(g["monto"], 2), "detalle": detalle if len(detalle) > 1 else []})
    filas.sort(key=lambda f: (f["clave"] == "bonificaciones", -abs(f["monto"])))
    return {"filas": filas, "total_factura": total_factura, "total": round(sum(f["monto"] for f in filas), 2), "flex_neto": round(flex_neto or 0.0, 2)}


def resumen_condensado_periodo_actual(access_token, cuenta_id, group="ML"):
    """
    Versión liviana de obtener_resumen_periodo pensada para paneles que
    solo necesitan un vistazo del período de facturación EN CURSO (no
    la página completa de /facturacion, que deja elegir un período
    viejo). Reutiliza el mismo caché de 10 minutos — si ya se visitó
    /facturacion en esta sesión, esto no pega de nuevo a la API.
    """
    periodos = obtener_periodos(access_token, cuenta_id, group)
    if not periodos:
        return None
    periodo_actual = periodos[0]
    key = periodo_actual.get("key")
    if not key:
        return None
    resumen = obtener_resumen_periodo(access_token, cuenta_id, key, group)
    if not resumen or not isinstance(resumen, dict):
        return None

    agrupada = agrupar_factura(resumen)
    periodo = periodo_actual.get("period", {})
    return {
        "filas": agrupada["filas"],
        "total_cargos_formateado": formatear_moneda(agrupada["total_factura"]),
        "en_curso": periodo_actual.get("period_status") == "OPEN",
        "date_from": periodo.get("date_from"),
        "date_to": periodo.get("date_to"),
    }

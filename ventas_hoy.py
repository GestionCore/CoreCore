"""
Ventas de un día conciliadas en tres etapas, a diferencia del panel de Mercado Libre (que mezcla todo):

    Ventas brutas  −  Canceladas / devueltas  =  Ventas netas

· NETAS = las filas vigentes de `ventas` (lo único que suma a facturación y ganancia).
· CANCELADAS / DEVUELTAS = lo que Mercado Libre canceló o reembolsó y el sync archivó en `ventas_retiradas` (ver ventas_sync): tanto las que ya estaban
  guardadas y se sacaron de `ventas` (motivo `cancelada`) como las que se crearon y cancelaron antes de que el sync las viera (`cancelada_sin_contar`).
· BRUTAS = netas + canceladas: todo lo que entró por la puerta ese día.
Cada etapa dice cuántas órdenes, cuántos compradores distintos (un carrito con varios ítems es UN comprador, y quien compra dos veces el mismo día también),
cuántas unidades y cuánta plata. El día es el de creación de la orden en hora argentina (`fecha_venta`), no el de la cancelación.

El acordeón agrupa por MODELO (la familia de Mercado Libre; sin familia, el título sin su talle) y, adentro, por VARIANTE (el color u otra versión + el talle o el
atributo que la distingue): la variante sale de los datos de Mercado Libre (`productos_variantes`), nunca de adivinar el título. Mismo criterio que la pantalla Costos.
Todo se lee con la conexión del usuario (RLS): cada cuenta ve solo lo suyo.
"""
from costos import nombres_de_variantes, parece_talle
from utils import formatear_moneda, limpiar_titulo_modelo, normalizar_talle, plural

# Las filas del día, de las dos tablas, con la misma forma. `ventas_retiradas` puede tener la misma línea archivada dos veces (dos sincronizaciones a la vez): se toma una.
_DIA = """
WITH dia AS (
    SELECT 'neta' AS estado, v.cuenta_id, v.id_orden, v.id_meli, COALESCE(v.id_variante, '') AS id_variante, v.titulo, v.cantidad,
           v.precio_venta AS precio, COALESCE(NULLIF(v.comprador_nickname, ''), v.id_orden) AS comprador, v.hora_venta::text AS hora
    FROM ventas v WHERE v.fecha_venta = %(fecha)s
    UNION ALL
    SELECT 'cancelada', r.cuenta_id, r.id_orden, r.fila->>'id_meli', COALESCE(r.fila->>'id_variante', ''), r.fila->>'titulo',
           COALESCE((r.fila->>'cantidad')::int, 1), COALESCE((r.fila->>'precio_venta')::numeric, 0),
           COALESCE(NULLIF(r.fila->>'comprador_nickname', ''), r.id_orden), r.fila->>'hora_venta'
    FROM (SELECT DISTINCT ON (id_orden, fila->>'id_meli') * FROM ventas_retiradas
          WHERE (fila->>'fecha_venta')::date = %(fecha)s ORDER BY id_orden, fila->>'id_meli', id) r
)
"""

_TOTALES = _DIA + """
SELECT estado, COUNT(DISTINCT id_orden), COUNT(DISTINCT comprador), COALESCE(SUM(cantidad), 0), COALESCE(SUM(precio * cantidad), 0)
FROM dia GROUP BY GROUPING SETS ((estado), ())
"""

_LINEAS = _DIA + """
SELECT d.estado, d.id_orden, d.id_meli, d.titulo, d.cantidad, d.precio, d.comprador, d.hora, pp.family_id, pv.talle, pv.etiqueta
FROM dia d
LEFT JOIN productos_padre pp ON pp.cuenta_id = d.cuenta_id AND pp.id_meli = d.id_meli
LEFT JOIN productos_variantes pv ON pv.cuenta_id = d.cuenta_id AND pv.id_variante = COALESCE(NULLIF(d.id_variante, ''), d.id_meli || '_unica')     -- sin variaciones la variante guardada es «<id>_unica»
ORDER BY d.hora DESC NULLS LAST
"""


def _bloque(ordenes=0, compradores=0, unidades=0, facturado=0.0):
    return {"ordenes": int(ordenes or 0), "compradores": int(compradores or 0), "unidades": int(unidades or 0), "facturado": round(float(facturado or 0), 2)}


def frase_conciliacion(brutas, canceladas, netas):
    """La cuenta en una línea, para el tooltip de la barra superior: «Ventas brutas: X | Canceladas/Devueltas: Y | Netas: Z»."""
    def dato(b):
        return f"{plural(b['ordenes'], 'orden', 'órdenes')} (${formatear_moneda(b['facturado'])})"
    return f"Ventas brutas: {dato(brutas)} | Canceladas/Devueltas: {dato(canceladas)} | Netas: {dato(netas)}"


def totales_del_dia(cursor, fecha):
    """
    {"brutas", "canceladas", "netas", "frase"} del día `fecha` (date o 'YYYY-MM-DD'). Una sola consulta; lo usan la barra superior (cada pocos segundos) y el
    panel del Dashboard. Los compradores de las brutas se cuentan sobre las dos etapas juntas (alguien que compró y canceló es un comprador, no dos).
    """
    cursor.execute(_TOTALES, {"fecha": fecha})
    por_estado = {estado: _bloque(*resto) for estado, *resto in cursor.fetchall()}
    brutas, canceladas, netas = por_estado.get(None, _bloque()), por_estado.get("cancelada", _bloque()), por_estado.get("neta", _bloque())
    return {"brutas": brutas, "canceladas": canceladas, "netas": netas, "frase": frase_conciliacion(brutas, canceladas, netas)}


def _rotulo(talle, etiqueta):
    """Lo que distingue a una publicación dentro de su variante: el talle y, si no hay talle (un celular, una pintura), el atributo («128 GB / Rosa», «4 L»)."""
    talle = normalizar_talle(talle)
    if talle != "Único":
        return talle
    return etiqueta if etiqueta not in (None, "", "Única") else ""


def _acumulador():
    return {"ordenes": set(), "unidades": 0, "facturado": 0.0}


def _sumar(acumulador, linea):
    acumulador["ordenes"].add(linea["id_orden"])
    acumulador["unidades"] += linea["cantidad"]
    acumulador["facturado"] += linea["precio"] * linea["cantidad"]


def _cerrar(acumulador):
    return {"ordenes": len(acumulador["ordenes"]), "unidades": acumulador["unidades"], "facturado": round(acumulador["facturado"], 2)}


def agrupar_por_modelo(lineas):
    """
    El acordeón del día. `lineas` = [{estado: 'neta'|'cancelada', id_orden, titulo, cantidad, precio, family_id, talle, etiqueta}].
    Devuelve los modelos, el que más facturó primero (los que solo tuvieron canceladas, al final), cada uno con sus variantes:
    [{"nombre", "netas": {ordenes, unidades, facturado}, "canceladas": {...}, "variantes": [{"etiqueta", "netas", "canceladas"}]}].
    """
    familias = {}
    for l in lineas:
        titulo_modelo = limpiar_titulo_modelo(l["titulo"], l["talle"]) or "Sin nombre"
        clave = ("familia", l["family_id"]) if l.get("family_id") else ("titulo", titulo_modelo.lower())
        familias.setdefault(clave, {}).setdefault(titulo_modelo, []).append({**l, "rotulo": _rotulo(l["talle"], l["etiqueta"])})

    modelos = []
    for por_titulo in familias.values():
        nombre, etiquetas = nombres_de_variantes(list(por_titulo))
        if len(por_titulo) > 1 and all(parece_talle(e) for e in etiquetas.values()):
            # Lo único que distingue a los «modelos» son talles escritos en medio del título: es UNA variante con varios talles (igual que en Costos)
            por_titulo = {nombre: [{**l, "rotulo": l["rotulo"] or etiquetas[t]} for t, ls in por_titulo.items() for l in ls]}
            etiquetas = {nombre: ""}
        totales = {"neta": _acumulador(), "cancelada": _acumulador()}
        variantes = {}
        for titulo, ls in por_titulo.items():
            for l in ls:
                nombre_variante = " · ".join(p for p in (etiquetas[titulo], l["rotulo"]) if p) or "Única"
                v = variantes.setdefault(nombre_variante, {"neta": _acumulador(), "cancelada": _acumulador()})
                _sumar(v[l["estado"]], l)
                _sumar(totales[l["estado"]], l)
        filas = [{"etiqueta": e, "netas": _cerrar(v["neta"]), "canceladas": _cerrar(v["cancelada"])} for e, v in variantes.items()]
        filas.sort(key=lambda f: (-f["netas"]["unidades"], -f["canceladas"]["unidades"], f["etiqueta"].lower()))
        modelos.append({"nombre": nombre, "netas": _cerrar(totales["neta"]), "canceladas": _cerrar(totales["cancelada"]), "variantes": filas})
    modelos.sort(key=lambda m: (-m["netas"]["facturado"], -m["canceladas"]["facturado"], m["nombre"].lower()))
    return modelos


def lineas_del_dia(cursor, fecha):
    """Las líneas de venta del día (netas y canceladas) con la familia y la variante de Mercado Libre de cada una."""
    cursor.execute(_LINEAS, {"fecha": fecha})
    return [
        {"estado": estado, "id_orden": id_orden, "id_meli": id_meli, "titulo": titulo, "cantidad": int(cantidad or 1), "precio": float(precio or 0),
         "comprador": comprador, "hora": (hora or "")[:5], "family_id": family_id, "talle": talle, "etiqueta": etiqueta}
        for estado, id_orden, id_meli, titulo, cantidad, precio, comprador, hora, family_id, talle, etiqueta in cursor.fetchall()
    ]


def conciliar_dia(cursor, fecha):
    """Todo junto para el panel del Dashboard: las tres etapas y el acordeón por modelo y variante."""
    return {**totales_del_dia(cursor, fecha), "fecha": str(fecha), "modelos": agrupar_por_modelo(lineas_del_dia(cursor, fecha))}

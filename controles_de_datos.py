"""
Controles de los DATOS REALES de cada cuenta (para /admin/salud): lo que las pruebas automáticas, que usan datos armados a mano, no pueden ver.

El 2026-10-14 apareció un error que existía desde el principio: el 97 % de las ventas de la cuenta real no encontraba su variante, y «Lo que tenés que reponer» salía vacío sin que nada avisara.
Estos controles miran los números de verdad y avisan cuando algo no cierra: ventas que no encuentran su variante ni su publicación, pagos que nunca se informaron, diferencia contra lo que Mercado
Pago depositó, envíos sin resolver, publicaciones sin datos básicos y horas sin normalizar. Solo lectura. `reunir` hace las consultas; `evaluar` decide qué avisar (puro, con sus pruebas).
"""

DIAS_VENTANA = 90
UMBRAL_SIN_VARIANTE = 0.10        # más del 10 % de las ventas sin variante: el sincronizador del catálogo no está funcionando
UMBRAL_SIN_PUBLICACION = 0.10
UMBRAL_SIN_PAGO = 0.15            # de las ventas de hace más de 20 días: el pago ya tendría que estar informado
CONCILIACION_AVISA = 2.0          # % de diferencia entre lo que CoreLux calcula que depositan y lo que depositaron
CONCILIACION_FALLA = 5.0
MIN_VENTAS_PARA_CONCILIAR = 30

_CONSULTAS = {
    "ventas": "SELECT COUNT(*) FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND fecha_venta >= current_date - 90",
    "sin_variante": """SELECT COUNT(*) FROM ventas v WHERE v.cuenta_id = %(c)s AND v.origen = 'meli' AND v.fecha_venta >= current_date - 90
        AND NOT EXISTS (SELECT 1 FROM productos_variantes pv WHERE pv.cuenta_id = v.cuenta_id AND pv.id_variante = COALESCE(NULLIF(v.id_variante, ''), v.id_meli || '_unica'))""",
    "sin_publicacion": """SELECT COUNT(*) FROM ventas v WHERE v.cuenta_id = %(c)s AND v.origen = 'meli' AND v.fecha_venta >= current_date - 90
        AND NOT EXISTS (SELECT 1 FROM productos_padre p WHERE p.cuenta_id = v.cuenta_id AND p.id_meli = v.id_meli)""",
    "viejas": "SELECT COUNT(*), COUNT(*) FILTER (WHERE neto_recibido IS NULL) FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND fecha_venta BETWEEN current_date - 90 AND current_date - 20",
    "conciliacion": """SELECT COUNT(*), COALESCE(SUM(neto_recibido), 0),
        COALESCE(SUM(precio_venta * cantidad - cargo_venta - (costo_envio - COALESCE(costo_flex, 0)) - COALESCE(retenciones, 0)), 0)
        FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND neto_recibido IS NOT NULL AND fecha_venta >= current_date - 60""",
    "envios_pendientes": "SELECT COUNT(*) FROM ventas WHERE cuenta_id = %(c)s AND origen = 'meli' AND envio_estado = 'pendiente' AND fecha_venta < current_date - 10",
    "activas": "SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %(c)s AND estado = 'active'",
    "activas_sin_variantes": """SELECT COUNT(*) FROM productos_padre p WHERE p.cuenta_id = %(c)s AND p.estado = 'active'
        AND NOT EXISTS (SELECT 1 FROM productos_variantes v WHERE v.id_padre = p.id)""",
    "activas_sin_categoria": "SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %(c)s AND estado = 'active' AND category_id IS NULL",
    "activas_sin_precio": "SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %(c)s AND estado = 'active' AND COALESCE(precio, 0) <= 0",
    "activas_sin_costo": "SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %(c)s AND estado = 'active' AND COALESCE(precio_costo, 0) = 0",
    "horas_sin_normalizar": "SELECT COUNT(*) FROM ventas WHERE cuenta_id = %(c)s AND hora_normalizada = false",
    "stock_negativo": "SELECT COUNT(*) FROM productos_variantes v JOIN productos_padre p ON p.id = v.id_padre WHERE p.cuenta_id = %(c)s AND (v.stock_propio < 0 OR v.stock_full < 0)",
}


def reunir(cursor, cuenta_id):
    """Los números crudos de una cuenta (una consulta por control, todas con cuenta_id explícito)."""
    v = {}
    for nombre, sql in _CONSULTAS.items():
        cursor.execute(sql, {"c": cuenta_id})
        fila = cursor.fetchone()
        v[nombre] = tuple(fila) if len(fila) > 1 else fila[0]
    v["viejas"], v["viejas_sin_pago"] = v["viejas"]
    ventas, depositado, esperado = v.pop("conciliacion")
    v["conciliacion_ventas"], v["conciliacion_depositado"], v["conciliacion_esperado"] = ventas, float(depositado), float(esperado)
    return v


def _porcentaje(parte, total):
    """«10,2» (con coma, como se ve en pantalla)."""
    return str(round(parte / total * 100, 1) if total else 0.0).replace(".", ",")


def evaluar(v):
    """
    La lista de hallazgos [{clave, tono, titulo, detalle}] de una cuenta a partir de `reunir`; vacía si todo cierra. `tono`: danger = algo está roto, warn = para mirar.
    """
    hallazgos = []

    def _agregar(clave, tono, titulo, detalle):
        hallazgos.append({"clave": clave, "tono": tono, "titulo": titulo, "detalle": detalle})

    ventas = v["ventas"] or 0
    if ventas and v["sin_variante"] / ventas > UMBRAL_SIN_VARIANTE:
        _agregar("sin_variante", "danger", f"{v['sin_variante']} de {ventas} ventas no encuentran su variante ({_porcentaje(v['sin_variante'], ventas)} %)",
                 "Stock, Despacho, «qué reponer» y la ganancia por variante dependen de eso: revisar la sincronización del catálogo (productos_variantes).")
    if ventas and v["sin_publicacion"] / ventas > UMBRAL_SIN_PUBLICACION:
        _agregar("sin_publicacion", "warn", f"{v['sin_publicacion']} de {ventas} ventas son de publicaciones que ya no están en el catálogo ({_porcentaje(v['sin_publicacion'], ventas)} %)",
                 "Puede ser normal si se cerraron publicaciones; si no, el catálogo no está sincronizando todo.")
    if v["viejas"] and v["viejas_sin_pago"] / v["viejas"] > UMBRAL_SIN_PAGO:
        _agregar("sin_pago", "warn", f"{v['viejas_sin_pago']} de {v['viejas']} ventas de hace más de 20 días no tienen el pago informado ({_porcentaje(v['viejas_sin_pago'], v['viejas'])} %)",
                 "Sin el pago no se puede conciliar contra lo depositado ni mostrar cuándo se acredita: revisar el relleno de datos de pago (ventas_sync).")
    if v["conciliacion_ventas"] >= MIN_VENTAS_PARA_CONCILIAR and v["conciliacion_esperado"]:
        diferencia = (v["conciliacion_depositado"] - v["conciliacion_esperado"]) / abs(v["conciliacion_esperado"]) * 100
        if abs(diferencia) >= CONCILIACION_AVISA:
            _agregar("conciliacion", "danger" if abs(diferencia) >= CONCILIACION_FALLA else "warn",
                     f"Lo depositado difiere {str(abs(round(diferencia, 1))).replace('.', ',')} % de lo que CoreLux calcula ({'más' if diferencia > 0 else 'menos'} plata de la esperada)",
                     "La ganancia real se apoya en que cierre con el depósito: revisar cargos, envíos y retenciones de las ventas de los últimos 60 días.")
    if v["envios_pendientes"]:
        _agregar("envios_pendientes", "warn", f"{v['envios_pendientes']} ventas de hace más de 10 días siguen con el costo de envío sin resolver",
                 "El costo de envío real se completa de a poco en cada sincronización; si no baja, algo lo está frenando.")
    if v["activas_sin_variantes"]:
        _agregar("activas_sin_variantes", "danger", f"{v['activas_sin_variantes']} publicaciones activas no tienen ninguna variante guardada",
                 "No se puede mostrar ni editar su stock: revisar la sincronización de esas publicaciones.")
    faltan_datos = v["activas_sin_categoria"] + v["activas_sin_precio"]
    if faltan_datos:
        _agregar("activas_incompletas", "warn", f"{faltan_datos} publicaciones activas sin categoría o sin precio",
                 "Mercado, Precios y Calidad no pueden trabajar con ellas.")
    if v["horas_sin_normalizar"]:
        _agregar("horas", "warn", f"{v['horas_sin_normalizar']} ventas con la hora sin normalizar", "Corre normalizar_horas.py (vista previa por defecto; --aplicar para corregir).")
    if v["stock_negativo"]:
        _agregar("stock_negativo", "danger", f"{v['stock_negativo']} variantes con stock negativo", "Un stock negativo no existe: revisar de dónde viene.")
    if v["activas"] and v["activas_sin_costo"]:
        _agregar("sin_costo", "warn", f"{v['activas_sin_costo']} de {v['activas']} publicaciones activas sin costo de fabricación",
                 "No es un error de datos: es lo que más infla la ganancia que ve la persona (se carga en Costos).")
    return hallazgos

"""
El contexto de la cuenta para el asistente de IA: una ficha corta del negocio de la persona (qué vende, qué tiene activado, sus preferencias y las fechas comerciales que se vienen) que se
suma al prompt para que no haya que preguntarle lo básico («¿qué vendés?», «¿usás Flex?») y para que los consejos sean de SU negocio.

Reglas:
  · Es contexto, no datos de plata: no lleva ninguna cifra de dinero (para eso están las herramientas, que calculan como las pantallas).
  · Se arma en el servidor con la cuenta de la sesión (RLS + `cuenta_id` explícito) y se guarda 15 minutos en `cache_db` por cuenta: casi siempre cuesta una lectura.
  · Los nombres de productos y categorías son texto de la propia cuenta o de Mercado Libre: se limpian (una línea, largo acotado, sin marcas de botones) y el prompt avisa que son DATOS.
  · Nunca levanta una excepción: si algo falla, el asistente sigue sin contexto.
"""
import re
from datetime import timedelta

import cache_db
import costos
import db
import fiscal
import tendencias
from utils import hoy_argentina

TTL_SEGUNDOS = 15 * 60
CLAVE = "asistente_contexto"
DIAS_DE_FECHAS_COMERCIALES = 45
MAX_LARGO_NOMBRE = 70
NOMBRES_DE_LOGISTICA = {"fulfillment": "FULL", "self_service": "Flex", "sin_dato": "sin dato"}
NOMBRES_DE_CAPACIDAD = (("ads", "Publicidad (Product Ads)"), ("flex", "Flex"), ("full", "FULL"), ("catalogo", "publicaciones de catálogo"))


def _limpio(texto, largo=MAX_LARGO_NOMBRE):
    """Una línea, sin caracteres de control ni marcas de botón, de largo acotado."""
    texto = re.sub(r"\[\[|\]\]|[\x00-\x1f\x7f]", " ", str(texto or ""))
    return re.sub(r"\s+", " ", texto).strip()[:largo]


def _corto(texto, largo=MAX_LARGO_NOMBRE):
    """El texto limpio y, si es largo, cortado en el límite de una palabra con «…» (no a mitad de palabra)."""
    texto = _limpio(texto, 400)
    if len(texto) <= largo:
        return texto
    return texto[:largo].rsplit(" ", 1)[0].rstrip(" ,.-") + "…"


def _estado_de(capacidades, clave):
    valor = (capacidades or {}).get(clave)
    return "sí" if valor is True else ("no" if valor is False else "sin confirmar")


def _mezcla_de_logistica(filas):
    """De [(tipo, unidades)] el reparto en % por modalidad, de mayor a menor: «FULL 72 %, Flex 26 %»."""
    total = sum(int(u or 0) for _, u in filas)
    if total <= 0:
        return None
    ordenadas = sorted(((NOMBRES_DE_LOGISTICA.get(t, "Correo / Mercado Envíos"), int(u or 0)) for t, u in filas), key=lambda x: -x[1])
    unidas = {}
    for nombre, unidades in ordenadas:
        unidas[nombre] = unidas.get(nombre, 0) + unidades
    return ", ".join(f"{n} {round(u / total * 100)} %" for n, u in sorted(unidas.items(), key=lambda x: -x[1]) if round(u / total * 100) > 0)


def _modelos_que_mas_venden(filas, cuantos=3):
    """De [(familia, título, unidades)] los nombres de los modelos con más unidades (todas las variantes de una familia juntas, con su nombre común)."""
    familias = {}
    for familia, titulo, unidades in filas:
        f = familias.setdefault(familia, {"titulos": [], "unidades": 0})
        f["titulos"].append(titulo or "")
        f["unidades"] += int(unidades or 0)
    nombres = []
    for f in sorted(familias.values(), key=lambda f: -f["unidades"])[:cuantos]:
        nombre, _ = costos.nombres_de_variantes(list(dict.fromkeys(t for t in f["titulos"] if t)))
        nombres.append(_corto(nombre or (f["titulos"][0] if f["titulos"] else "")))
    return [n for n in nombres if n]


def _fechas_comerciales(hoy):
    """Las fechas comerciales de los próximos días: «Día de la Madre (18/10, en 4 días)»."""
    eventos = []
    for anio in (hoy.year, hoy.year + 1):
        for e in tendencias.obtener_calendario_estacional(anio):
            dias = (e["fecha"] - hoy).days
            if 0 <= dias <= DIAS_DE_FECHAS_COMERCIALES:
                eventos.append((dias, e))
    texto = []
    for dias, e in sorted(eventos, key=lambda x: x[0]):
        cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} días")
        texto.append(f"{e['nombre']} ({e['fecha'].strftime('%d/%m')}, {cuando}; {e['categoria_sugerida']})")
    return "; ".join(texto) if texto else None


def _armar_texto(cursor, usuario_id, cuenta_id, hoy):
    cursor.execute("SELECT nombre_negocio, capacidades, margen_minimo, condicion_fiscal, dolar_manual, conectada_en FROM cuentas_meli WHERE id = %s AND usuario_id = %s", (cuenta_id, usuario_id))
    cuenta = cursor.fetchone()
    if not cuenta:
        return ""
    negocio, capacidades, margen_minimo, condicion, dolar_manual, conectada = cuenta
    cursor.execute("SELECT COUNT(*) FILTER (WHERE estado = 'active'), COUNT(*) FILTER (WHERE estado = 'paused') FROM productos_padre WHERE cuenta_id = %s", (cuenta_id,))
    activas, pausadas = cursor.fetchone()
    cursor.execute("""SELECT COALESCE(c.nombre, p.category_id), COUNT(*) FROM productos_padre p LEFT JOIN mercado_categorias c ON c.category_id = p.category_id
                      WHERE p.cuenta_id = %s AND p.estado = 'active' AND p.category_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (cuenta_id,))
    categorias = [_limpio(r[0], 50) for r in cursor.fetchall() if r[0]]
    cursor.execute("SELECT MIN(fecha_venta) FROM ventas WHERE cuenta_id = %s AND origen = 'meli'", (cuenta_id,))
    primera_venta = cursor.fetchone()[0]
    desde = hoy - timedelta(days=29)
    cursor.execute("""SELECT COALESCE(p.family_id, v.id_meli), p.titulo, SUM(v.cantidad) FROM ventas v LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
                      WHERE v.cuenta_id = %s AND v.origen = 'meli' AND v.fecha_venta BETWEEN %s AND %s GROUP BY 1, 2""", (cuenta_id, desde, hoy))
    modelos = _modelos_que_mas_venden(cursor.fetchall())
    cursor.execute("""SELECT COALESCE(NULLIF(tipo_logistica, ''), 'sin_dato'), SUM(cantidad) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND fecha_venta BETWEEN %s AND %s GROUP BY 1""", (cuenta_id, desde, hoy))
    logistica = _mezcla_de_logistica(cursor.fetchall())

    lineas = []
    if negocio:
        lineas.append(f"- Nombre del negocio: {_limpio(negocio, 60)}.")
    if conectada:
        dia_de_conexion = conectada.date() if hasattr(conectada, "date") else conectada
        lineas.append(f"- Conectada a CoreLux hace {max((hoy - dia_de_conexion).days, 0)} días" + (f"; primera venta registrada el {primera_venta.strftime('%d/%m/%Y')}." if primera_venta else "."))
    lineas.append(f"- Publicaciones: {int(activas or 0)} activas y {int(pausadas or 0)} pausadas." + (f" Categorías donde más publica: {', '.join(categorias)}." if categorias else ""))
    if modelos:
        lineas.append("- Lo que más vendió en los últimos 30 días: " + "; ".join(f"«{m}»" for m in modelos) + ".")
    if logistica:
        lineas.append(f"- Cómo entrega (unidades de los últimos 30 días): {logistica}.")
    lineas.append("- Tiene activado: " + ", ".join(f"{nombre} {_estado_de(capacidades, clave)}" for clave, nombre in NOMBRES_DE_CAPACIDAD) + " («sin confirmar» = todavía no se sabe).")
    lineas.append(f"- Preferencias: margen mínimo de referencia {round(float(margen_minimo))} %; costos en dólares con " + ("un dólar propio" if dolar_manual else "el dólar MEP automático") + f"; condición fiscal: {fiscal.etiqueta(condicion) if condicion else 'sin declarar'}.")
    fechas = _fechas_comerciales(hoy)
    if fechas:
        lineas.append(f"- Fechas comerciales que se vienen: {fechas}.")
    return "\n".join(lineas)


def armar(usuario_id, cuenta_id, hoy=None):
    """El texto del contexto (varias líneas que empiezan con «- ») o «» si no se pudo armar. Se guarda 15 minutos por cuenta."""
    hoy = hoy or hoy_argentina()
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            hit, valor = cache_db.leer(cursor, cuenta_id, CLAVE, firma=hoy.isoformat(), ttl_segundos=TTL_SEGUNDOS)
            if hit and isinstance(valor, str):
                return valor
            texto = _armar_texto(cursor, usuario_id, cuenta_id, hoy)
            if texto:
                cache_db.guardar(cursor, cuenta_id, CLAVE, texto, firma=hoy.isoformat())
            return texto
    except Exception as e:
        print(f"[Asistente] ⚠️ No se pudo armar el contexto de la cuenta: {type(e).__name__}: {e}")
        return ""

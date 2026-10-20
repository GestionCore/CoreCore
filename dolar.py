"""
Cotización del dólar: a cuánto convierte CoreLux los costos que una persona carga en dólares (Paso 2 del pivot; hoy solo se muestra y se elige en «Mi cuenta»).

Dos fuentes libres, sin clave (respondieron las dos desde Fly en el sondeo):
  · dolarapi.com `/v1/dolares` — oficial, blue y bolsa (= dólar MEP). Es la fuente principal.
  · api.bluelytics.com.ar `/v2/latest` — respaldo: da oficial y blue pero NO MEP. Si dolarapi cae, el MEP queda con el último valor guardado y se avisa cuántos días tiene.

Cada cuenta usa uno de dos:
  · «Cotización automática»: el dólar MEP (casa `bolsa`), precio de VENTA —lo que cuesta comprar un dólar para reponer mercadería—, el último guardado;
  · «Dólar manual»: lo que la persona indica que paga (`cuentas_meli.dolar_manual`). Sin valor manual (NULL) se usa el automático.
Se guarda la serie diaria (`cotizaciones_dolar`, una fila por día y casa: la tarea del scheduler la actualiza varias veces por día) para poder valuar con el dólar de un día pasado.
Nunca se inventa una cotización: sin dato (ni manual ni MEP guardado) el valor activo es None y la pantalla lo dice.
"""
import re
from datetime import datetime, timezone

import requests

from utils import ARGENTINA, hoy_argentina

URL_DOLARAPI = "https://dolarapi.com/v1/dolares"
URL_BLUELYTICS = "https://api.bluelytics.com.ar/v2/latest"
CASAS = ("oficial", "blue", "bolsa")
CASA_MEP = "bolsa"
TIMEOUT_SEGUNDOS = 10
DIAS_PARA_AVISAR_VIEJA = 4          # un MEP guardado hace más de 4 días se marca desactualizado (un fin de semana largo llega a 3)
MANUAL_MINIMO = 10                  # a menos de $10 por dólar casi seguro faltó un punto de miles: se rechaza
MANUAL_MAXIMO = 1_000_000


def _get(url):
    """El JSON de una URL pública, o levanta una excepción (se prueba reemplazando esta función)."""
    r = requests.get(url, timeout=TIMEOUT_SEGUNDOS, headers={"Accept": "application/json", "User-Agent": "CoreLux"})
    r.raise_for_status()
    return r.json()


def _positivo(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    return round(v, 2) if v == v and 0 < v < MANUAL_MAXIMO else None


def _instante(texto):
    """La hora que informa la fuente como datetime con zona (None si no viene o no se entiende)."""
    try:
        dt = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parsear_dolarapi(datos):
    """{casa: {"compra", "venta", "actualizado"}} de la respuesta de dolarapi.com; se descartan las casas que no interesan y las que traen una venta que no es un número positivo."""
    salida = {}
    for fila in datos if isinstance(datos, list) else []:
        casa = str((fila or {}).get("casa") or "").lower()
        venta = _positivo((fila or {}).get("venta"))
        if casa in CASAS and venta is not None:
            salida[casa] = {"compra": _positivo(fila.get("compra")), "venta": venta, "actualizado": _instante(fila.get("fechaActualizacion"))}
    return salida


def parsear_bluelytics(datos):
    """Lo mismo con Bluelytics: solo oficial y blue (no publica el MEP)."""
    salida = {}
    if not isinstance(datos, dict):
        return salida
    actualizado = _instante(datos.get("last_update"))
    for casa in ("oficial", "blue"):
        bloque = datos.get(casa)
        venta = _positivo((bloque or {}).get("value_sell")) if isinstance(bloque, dict) else None
        if venta is not None:
            salida[casa] = {"compra": _positivo(bloque.get("value_buy")), "venta": venta, "actualizado": actualizado}
    return salida


def traer_cotizaciones(get=None):
    """
    Las cotizaciones de hoy: ({casa: {"compra", "venta", "actualizado", "fuente"}}, [errores]). Primero dolarapi; lo que le falte (si cayó, todo) se completa con Bluelytics, que no tiene
    MEP: el MEP nunca sale de otra casa. Una fuente caída no frena a la otra ni levanta una excepción: queda anotada en la lista de errores.
    """
    get = get or _get
    cotizaciones, errores = {}, []
    for nombre, url, parsear in (("dolarapi", URL_DOLARAPI, parsear_dolarapi), ("bluelytics", URL_BLUELYTICS, parsear_bluelytics)):
        if all(c in cotizaciones for c in CASAS):
            break
        try:
            for casa, dato in parsear(get(url)).items():
                cotizaciones.setdefault(casa, {**dato, "fuente": nombre})
        except Exception as e:
            errores.append(f"{nombre}: {type(e).__name__}: {e}")
    return cotizaciones, errores


def guardar_cotizaciones(cursor, fecha, cotizaciones):
    """Guarda (o actualiza) la fila del día de cada casa. Hay que llamarla con la conexión de administración (la tabla es global: la app solo la lee). Devuelve cuántas filas escribió."""
    for casa, c in cotizaciones.items():
        cursor.execute("""
            INSERT INTO cotizaciones_dolar (fecha, casa, compra, venta, fuente, actualizado_en) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))
            ON CONFLICT (fecha, casa) DO UPDATE SET compra = excluded.compra, venta = excluded.venta, fuente = excluded.fuente, actualizado_en = excluded.actualizado_en
        """, (fecha, casa, c.get("compra"), c["venta"], c["fuente"], c.get("actualizado")))
    return len(cotizaciones)


def normalizar_manual(valor):
    """
    El dólar manual como número con 2 decimales, o None si no sirve (vacío, texto, cero, negativo o fuera de MANUAL_MINIMO–MANUAL_MAXIMO). Entiende el formato argentino («1.480», «1480,50»):
    «1.480» son mil cuatrocientos ochenta, no uno con cuarenta y ocho; un número tan bajo se rechaza antes que guardarlo mal y multiplicar todos los costos en dólares por un valor absurdo.
    """
    try:
        texto = str(valor).strip().replace("$", "").replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
            texto = texto.replace(".", "")
        numero = _positivo(texto)
    except Exception:
        return None
    return numero if numero is not None and numero >= MANUAL_MINIMO else None


def ultimo_mep(cursor, hoy=None):
    """El último dólar MEP guardado: {"valor", "fecha", "actualizado_en", "dias", "desactualizado"} o None si todavía no hay ninguno. `dias` = días desde que la fuente lo actualizó."""
    cursor.execute("SELECT fecha, venta, actualizado_en, fuente FROM cotizaciones_dolar WHERE casa = %s ORDER BY fecha DESC LIMIT 1", (CASA_MEP,))
    fila = cursor.fetchone()
    if not fila:
        return None
    fecha, venta, actualizado, fuente = fila
    dias = max(0, ((hoy or hoy_argentina()) - actualizado.astimezone(ARGENTINA).date()).days) if actualizado else None
    return {"valor": float(venta), "fecha": fecha, "actualizado_en": actualizado, "fuente": fuente, "dias": dias, "desactualizado": bool(dias is not None and dias > DIAS_PARA_AVISAR_VIEJA)}


def cotizacion_activa(cursor, cuenta_id, hoy=None):
    """
    A cuánto convierte esta cuenta un dólar: {"modo": "manual" | "automatico", "valor": pesos por dólar o None, "manual": lo que indicó (o None), "mep": ultimo_mep() o None}.
    Con dólar manual manda ese; si no, el MEP; sin ninguno de los dos el valor es None (nunca un número supuesto).
    """
    cursor.execute("SELECT dolar_manual FROM cuentas_meli WHERE id = %s", (cuenta_id,))
    fila = cursor.fetchone()
    manual = float(fila[0]) if fila and fila[0] is not None else None
    mep = ultimo_mep(cursor, hoy)
    if manual is not None:
        return {"modo": "manual", "valor": manual, "manual": manual, "mep": mep}
    return {"modo": "automatico", "valor": mep["valor"] if mep else None, "manual": None, "mep": mep}


def para_pantalla(activa):
    """`cotizacion_activa` lista para la pantalla y para JSON: el dólar MEP con su hora dicha para personas («Hoy 09:30») y si está desactualizado."""
    from utils import cuando_corto
    mep = activa.get("mep")
    return {
        "modo": activa["modo"], "valor": activa["valor"], "manual": activa["manual"],
        "mep": {"valor": mep["valor"], "actualizado": cuando_corto(mep["actualizado_en"].astimezone(ARGENTINA)) if mep["actualizado_en"] else None,
                "fuente": mep["fuente"], "dias": mep["dias"], "desactualizado": mep["desactualizado"]} if mep else None,
    }


def guardar_modo(cursor, cuenta_id, modo, valor=None):
    """
    «automatico» deja el dólar manual en NULL; «manual» guarda el valor indicado. Devuelve (ok, mensaje). Un valor manual inválido no cambia nada.
    """
    if modo == "automatico":
        cursor.execute("UPDATE cuentas_meli SET dolar_manual = NULL WHERE id = %s", (cuenta_id,))
        return True, "Vas a usar la cotización automática (dólar MEP)."
    if modo == "manual":
        manual = normalizar_manual(valor)
        if manual is None:
            return False, f"Escribí cuánto pagás el dólar, por ejemplo 1480 (entre ${MANUAL_MINIMO} y ${MANUAL_MAXIMO:,}).".replace(",", ".")
        cursor.execute("UPDATE cuentas_meli SET dolar_manual = %s WHERE id = %s", (manual, cuenta_id))
        return True, "Guardamos el valor que elegiste."
    return False, "Elegí la cotización automática o indicá tu propio valor."


def actualizar(cursor, hoy=None, get=None):
    """
    Lo que corre el scheduler varias veces por día (con la conexión de administración): trae las cotizaciones y guarda la fila de hoy de cada casa. Devuelve un resumen
    {"guardadas": n, "casas": [...], "errores": [...]}. Si ninguna fuente respondió no escribe nada y las pantallas siguen con el último valor guardado.
    """
    cotizaciones, errores = traer_cotizaciones(get)
    guardadas = guardar_cotizaciones(cursor, hoy or hoy_argentina(), cotizaciones) if cotizaciones else 0
    return {"guardadas": guardadas, "casas": sorted(cotizaciones), "errores": errores}

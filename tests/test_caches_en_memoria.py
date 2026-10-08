"""
La clase de bug nº 1 de este proyecto (CLAUDE.md): estado en memoria compartido entre TODAS las cuentas en vez de aislado por cuenta; invisible con un usuario, real con dos.
Esta prueba inventaría todo contenedor mutable (dict / set / list / deque…) que un módulo crea a nivel de módulo, y exige que cada uno esté declarado abajo con su ALCANCE.
Si agregás un `_cache_*` nuevo, esta prueba falla hasta que lo clasifiques: pensá la clave (¿incluye la cuenta o un id que es de una sola cuenta?) o usá `cache_db` / `cache.leer()`.
"""
import ast
import glob
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLAMADAS = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter"}

# (archivo, nombre) -> por qué es seguro. Alcances aceptados: por cuenta_id; por un id que es de UNA sola cuenta (advertiser, user_id de MeLi, envío, pago);
# datos públicos de Mercado Libre iguales para todos (categorías, motivos de reclamo); infraestructura sin datos de cuentas (candados, límites por IP).
DECLARADOS = {
    ("ads.py", "_advertiser_cache"): "clave (cuenta_id, site_id)",
    ("ads.py", "_costos_cache"): "clave con advertiser_id: el advertiser es de una sola cuenta",
    ("ads.py", "_metricas_item_cache"): "clave con advertiser_id: el advertiser es de una sola cuenta",
    ("ads.py", "_anuncios_cache"): "clave con advertiser_id: el advertiser es de una sola cuenta; con tope de tamaño",
    ("calculadora_costos.py", "_cache_nombre_categoria"): "datos públicos de MeLi por id de categoría",
    ("calculadora_costos.py", "_cache_camino_categoria"): "datos públicos de MeLi por id de categoría",
    ("devoluciones_sync.py", "_cache_motivos_oficiales"): "texto público de cada motivo de reclamo, por id de motivo",
    ("embudo_conversion.py", "_cache_embudo"): "clave cuenta_id",
    ("facturacion.py", "_cache_periodos"): "clave cuenta_id",
    ("facturacion.py", "_cache_resumenes"): "clave (cuenta_id, grupo, período)",
    ("facturacion.py", "_cache_almacenamiento"): "clave (cuenta_id, grupo, período)",
    ("limitador.py", "_registro"): "contadores por IP/ruta: sin datos de cuentas",
    ("logistica.py", "_cache_horarios"): "clave (user_id de MeLi, tipo de logística): el user_id es de una sola cuenta",
    ("logistica.py", "_cache_flex_habilitado"): "clave user_id de MeLi: de una sola cuenta",
    ("sincronizador.py", "_candados_por_cuenta"): "un candado por cuenta_id",
    ("sincronizador.py", "_sincronizando"): "conjunto de cuenta_id con sync en curso",
    ("tendencias.py", "_categoria_cache"): "clave cuenta_id",
    ("tendencias.py", "_categoria_especifica_cache"): "clave cuenta_id",
    ("tendencias.py", "_cache_caminos_categoria"): "datos públicos de MeLi por id de categoría",
    ("tendencias.py", "_cache_resumen_categoria"): "datos públicos de MeLi por id de categoría",
    ("tendencias.py", "_cache_categorias_raiz"): "datos públicos de MeLi por sitio",
    ("ventas_sync.py", "_cache_shipment"): "id global de envío de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_cache_provincia_envio"): "id global de envío de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_cache_tipo_logistica"): "id global de envío de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_cache_ubicacion_envio"): "id global de envío de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_cache_costo_envio_vendedor"): "id global de envío de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_cache_pago"): "id global de pago de MeLi: lo ve una sola cuenta; con tope de tamaño",
    ("ventas_sync.py", "_logistica_sin_dato"): "ids de envío que MeLi no supo informar; con tope de tamaño",
    ("ventas_sync.py", "_pago_sin_dato"): "ids de orden que MeLi no supo informar; con tope de tamaño",
    ("ventas_sync.py", "_financiacion_sin_dato"): "ids de orden que MeLi no supo informar; con tope de tamaño",
    (os.path.join("auth", "token_manager.py"), "_candados_locales"): "un candado por cuenta_id",
}


def _contenedores_globales():
    encontrados = set()
    for patron in ("*.py", "auth/*.py"):
        for ruta in glob.glob(os.path.join(RAIZ, patron)):
            arbol = ast.parse(open(ruta, encoding="utf-8").read())
            for nodo in arbol.body:
                if isinstance(nodo, ast.Assign):
                    objetivos, valor = nodo.targets, nodo.value
                elif isinstance(nodo, ast.AnnAssign) and nodo.value is not None:
                    objetivos, valor = [nodo.target], nodo.value
                else:
                    continue
                for objetivo in objetivos:
                    if not isinstance(objetivo, ast.Name) or objetivo.id.isupper():
                        continue                                  # MAYÚSCULAS = constante de configuración
                    vacio = isinstance(valor, (ast.Dict, ast.List, ast.Set)) and not (getattr(valor, "keys", None) or getattr(valor, "elts", None))
                    llamada = isinstance(valor, ast.Call) and getattr(valor.func, "id", getattr(valor.func, "attr", "")) in LLAMADAS
                    if vacio or llamada:
                        encontrados.add((os.path.relpath(ruta, RAIZ), objetivo.id))
    return encontrados


def test_todo_contenedor_global_esta_clasificado_por_su_alcance():
    nuevos = sorted(_contenedores_globales() - set(DECLARADOS))
    assert not nuevos, (
        "Contenedor mutable a nivel de módulo sin clasificar: " + ", ".join(f"{a}:{n}" for a, n in nuevos)
        + ". Si guarda datos de una cuenta, la clave tiene que incluir la cuenta (o un id de una sola cuenta); mejor usá cache_db. Después declaralo en DECLARADOS con su alcance."
    )


def test_no_quedan_entradas_viejas_en_el_inventario():
    sobrantes = sorted(set(DECLARADOS) - _contenedores_globales())
    assert not sobrantes, f"Ya no existen (sacalas de DECLARADOS): {sobrantes}"
    assert all(len(motivo) > 10 for motivo in DECLARADOS.values())

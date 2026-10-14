"""
Una venta de una publicación SIN variaciones guarda `ventas.id_variante` vacío y su variante en `productos_variantes` se llama «<id_meli>_unica». Unir por `id_variante` a secas no encuentra
ninguna (en la cuenta real, 0 de 2.794 ventas): el stock en riesgo, la cobertura de variantes clave, el talle de cada venta y los rankings por modelo quedaban ciegos.
La clave sale de `utils.sql_variante_de_venta` (SQL) o `costos_moneda.variante_de_venta` (Python): estas pruebas impiden volver a unir «a secas».
"""
import glob
import os
import re
from datetime import timedelta

import pytest

import utils

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")


class _Revertir(Exception):
    pass


def test_la_clave_de_variante_de_una_venta_es_su_variante_o_el_id_con_unica():
    assert utils.sql_variante_de_venta("x") == "COALESCE(NULLIF(x.id_variante, ''), x.id_meli || '_unica')"
    import costos_moneda
    assert costos_moneda.variante_de_venta("MLA1", "") == "MLA1_unica" and costos_moneda.variante_de_venta("MLA1", None) == "MLA1_unica" and costos_moneda.variante_de_venta("MLA1", "99") == "99"


def test_ningun_modulo_une_las_ventas_con_las_variantes_por_id_variante_a_secas():
    pelado = re.compile(r"productos_variantes\s+(\w+)\s+ON\s+(?:\w+\.cuenta_id\s*=\s*\w+\.cuenta_id\s+AND\s+)?\1\.id_variante\s*=\s*(\w+)\.id_variante\b", re.I)
    malos = []
    for ruta in glob.glob(os.path.join(RAIZ, "*.py")) + glob.glob(os.path.join(RAIZ, "auth", "*.py")):
        for m in pelado.finditer(open(ruta, encoding="utf-8").read()):
            malos.append(f"{os.path.basename(ruta)}: {m.group(0)[:90]}")
    assert not malos, "Hay joins a productos_variantes por id_variante a secas (usar utils.sql_variante_de_venta):\n" + "\n".join(malos)


@CON_BASE
def test_el_stock_en_riesgo_cuenta_las_ventas_de_publicaciones_sin_variaciones():
    import analisis_stock
    import db
    from utils import hoy_argentina
    pid = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            id_meli = f"PRUEBA-RIE-{pid}"
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado) VALUES (%s, %s, 'Termo Prueba Riesgo', 1000, 'active') RETURNING id", (cuenta, id_meli))
            id_padre = cur.fetchone()[0]
            cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, stock_propio, stock_full, etiqueta) VALUES (%s, %s, %s, 2, 0, 'Azul')", (cuenta, f"{id_meli}_unica", id_padre))
            # 14 unidades en los últimos 14 días = 1 por día; con 2 en stock alcanza para 2 días: tiene que aparecer. La venta guarda id_variante VACÍO, como la real.
            cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen)
                           VALUES (%s, %s, %s, '', 'Termo Prueba Riesgo', 14, 1000, %s, 'meli')""", (cuenta, f"{id_meli}-O", id_meli, hoy_argentina() - timedelta(days=2)))
            riesgo = [r for r in analisis_stock.obtener_variantes_en_riesgo(cur) if r["id_meli"] == id_meli]
            assert len(riesgo) == 1 and riesgo[0]["dias_restantes"] == 2.0 and riesgo[0]["variante"] == "Azul"
            raise _Revertir()
    except _Revertir:
        pass


@CON_BASE
def test_la_variante_clave_sin_stock_se_detecta_con_ventas_de_publicaciones_sin_variaciones():
    import analisis_stock
    import db
    from utils import hoy_argentina
    pid = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            familia = f"FAM-RIE-{pid}"
            for sufijo, stock, vendidas, etiqueta in (("A", 0, 8, "Rojo"), ("B", 5, 2, "Azul")):
                id_meli = f"PRUEBA-CLA-{pid}{sufijo}"
                cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, family_id) VALUES (%s, %s, %s, 1000, 'active', %s) RETURNING id", (cuenta, id_meli, f"Funda Prueba {etiqueta}", familia))
                id_padre = cur.fetchone()[0]
                cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, stock_propio, stock_full, etiqueta) VALUES (%s, %s, %s, %s, 0, %s)", (cuenta, f"{id_meli}_unica", id_padre, stock, etiqueta))
                cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen)
                               VALUES (%s, %s, %s, '', 'Funda', %s, 100, %s, 'meli')""", (cuenta, f"{id_meli}-O", id_meli, vendidas, hoy_argentina() - timedelta(days=3)))
            clave = [c for c in analisis_stock.evaluar_cobertura_variantes(cur) if str(c["id_referencia"]).startswith(f"PRUEBA-CLA-{pid}")]
            assert len(clave) == 1 and clave[0]["variante"] == "Rojo" and clave[0]["aporta_pct"] == 80          # la roja aporta 8 de 10 y no tiene stock
            raise _Revertir()
    except _Revertir:
        pass

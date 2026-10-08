"""
Historial de precios, impacto de promociones y seguimientos de Tendencias leían una consulta POR FILA (hasta 80 viajes a la base para 40 cambios de precio). Ahora una sola consulta por pantalla.
Estas pruebas comparan, contra la base real y dentro de una transacción que se revierte, el resultado nuevo con el de la forma vieja (una consulta por fila): tienen que dar exactamente lo mismo.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

import historial_precios
import promociones
import tendencias
from utils import hoy_argentina


class _Revertir(Exception):
    pass


def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def _venta(cur, cuenta, n, id_meli, dia, cantidad):
    cur.execute("INSERT INTO ventas (cuenta_id, id_orden, id_meli, cantidad, fecha_venta) VALUES (%s, %s, %s, %s, %s)", (cuenta, f"PRUEBA-LOTE-{os.getpid()}-{n}", id_meli, cantidad, dia))


def _historial_viejo(cursor, dias_ventana=7, limite=40):
    """Copia de la versión anterior: dos consultas por cada cambio de precio."""
    cursor.execute("""
        SELECT hp.id_meli, hp.precio_anterior, hp.precio_nuevo, hp.fecha_cambio, p.titulo, p.thumbnail
        FROM historial_precios hp LEFT JOIN productos_padre p ON p.id_meli = hp.id_meli
        ORDER BY hp.fecha_cambio DESC LIMIT %s
    """, (limite,))
    resultado = []
    for id_meli, anterior, nuevo, fecha_cambio, titulo, thumbnail in cursor.fetchall():
        f = fecha_cambio if hasattr(fecha_cambio, "date") else datetime.strptime(str(fecha_cambio)[:10], "%Y-%m-%d")
        cursor.execute("SELECT COALESCE(SUM(cantidad), 0) FROM ventas WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s",
                       (id_meli, (f - timedelta(days=dias_ventana)).strftime("%Y-%m-%d"), (f - timedelta(days=1)).strftime("%Y-%m-%d")))
        antes = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COALESCE(SUM(cantidad), 0) FROM ventas WHERE id_meli = %s AND fecha_venta BETWEEN %s AND %s",
                       (id_meli, f.strftime("%Y-%m-%d"), (f + timedelta(days=dias_ventana)).strftime("%Y-%m-%d")))
        despues = cursor.fetchone()[0] or 0
        resultado.append((id_meli, f.strftime("%Y-%m-%d"), antes, despues))
    return resultado


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_el_historial_de_precios_en_lote_da_lo_mismo_que_consulta_por_consulta():
    import db
    usuario, cuenta = _cuenta()
    hoy = hoy_argentina()
    a, b = f"MLA-PRUEBA-LOTE-{os.getpid()}-A", f"MLA-PRUEBA-LOTE-{os.getpid()}-B"
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            ahora = datetime.now(timezone.utc)
            for id_meli, dias in ((a, 10), (a, 3), (b, 5), (b, 0)):
                cur.execute("INSERT INTO historial_precios (cuenta_id, id_meli, precio_anterior, precio_nuevo, fecha_cambio) VALUES (%s, %s, 100, 120, %s)", (cuenta, id_meli, ahora - timedelta(days=dias)))
            n = 0
            for id_meli, dia, cant in ((a, 14, 2), (a, 11, 1), (a, 9, 5), (a, 4, 3), (a, 2, 4), (a, 0, 1), (b, 8, 7), (b, 6, 1), (b, 5, 2), (b, 1, 9)):
                n += 1
                _venta(cur, cuenta, n, id_meli, hoy - timedelta(days=dia), cant)

            nuevo = [(r["id_meli"], r["fecha_cambio"], r["unidades_antes"], r["unidades_despues"]) for r in historial_precios.obtener_historial_con_impacto(cur)]
            viejo = _historial_viejo(cur)
            propios_nuevo = sorted(t for t in nuevo if "PRUEBA-LOTE" in t[0])
            propios_viejo = sorted(t for t in viejo if "PRUEBA-LOTE" in t[0])
            assert len(propios_nuevo) == 4 and propios_nuevo == propios_viejo
            assert nuevo == viejo                                                      # y el orden y todo lo demás de la pantalla, igual
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_el_impacto_de_promociones_en_lote_da_lo_mismo_que_consulta_por_consulta():
    import db
    usuario, cuenta = _cuenta()
    hoy = hoy_argentina()
    a, b = f"MLA-PRUEBA-LOTE-{os.getpid()}-A", f"MLA-PRUEBA-LOTE-{os.getpid()}-B"
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            cur.execute("INSERT INTO historial_promociones (cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_inicio, fecha_fin, promedio_diario_previo, activo) VALUES (%s,%s,'A',100,80,%s,%s,1.5,false)",
                        (cuenta, a, hoy - timedelta(days=12), hoy - timedelta(days=5)))
            cur.execute("INSERT INTO historial_promociones (cuenta_id, id_meli, titulo, precio_original, precio_promo, fecha_inicio, fecha_fin, promedio_diario_previo, activo) VALUES (%s,%s,'B',100,80,%s,NULL,0,true)",
                        (cuenta, b, hoy - timedelta(days=4)))
            for n, (id_meli, dia, cant) in enumerate(((a, 13, 4), (a, 10, 2), (a, 6, 3), (a, 3, 8), (b, 5, 1), (b, 3, 2), (b, 0, 6)), start=1):
                _venta(cur, cuenta, n, id_meli, hoy - timedelta(days=dia), cant)

            nuevo = {r["id_meli"]: r for r in promociones.obtener_impacto_promociones(cur)}
            # Referencia a mano: A (hace 12 → hace 5 días, ventas de hace 10 y 6 = 5 u.), B (hace 4 días → hoy, ventas de hace 3 y hoy = 8 u.)
            assert nuevo[a]["unidades_durante"] == 5 and nuevo[a]["promedio_durante"] == round(5 / 7, 2)
            assert nuevo[b]["unidades_durante"] == 8 and nuevo[b]["promedio_durante"] == round(8 / 4, 2)
            assert nuevo[a]["variacion_pct"] == round((round(5 / 7, 2) - 1.5) / 1.5 * 100, 1) and nuevo[b]["variacion_pct"] is None      # B venía sin ventas previas: no hay porcentaje
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_los_seguimientos_de_tendencias_juntan_sus_historiales_en_una_consulta():
    import db
    usuario, cuenta = _cuenta()
    hoy = hoy_argentina()
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            ids = []
            for i in range(3):
                cur.execute("INSERT INTO tendencias_seguimiento (cuenta_id, tipo, valor, etiqueta, automatico) VALUES (%s, 'termino', %s, %s, false) RETURNING id",
                            (cuenta, f"zz-prueba-lote-{os.getpid()}-{i}", f"Prueba {i}"))
                ids.append(cur.fetchone()[0])
            # 0: sin historial; 1: dos puntos (100 → 150 = +50 %); 2: un punto viejo (fuera de la ventana de 60 días) y uno reciente
            for sid, dia, pub, precio in ((ids[1], 10, 100, 1000), (ids[1], 1, 150, 1100), (ids[2], 90, 10, 500), (ids[2], 2, 40, 600)):
                cur.execute("INSERT INTO tendencias_snapshots (cuenta_id, seguimiento_id, fecha, total_publicaciones, ventas_muestra, precio_promedio) VALUES (%s, %s, %s, %s, 3, %s)",
                            (cuenta, sid, hoy - timedelta(days=dia), pub, precio))
            lista = {s["id"]: s for s in tendencias.listar_seguimientos_con_historial(cur, cuenta)}
            assert lista[ids[0]]["serie"] == [] and lista[ids[0]]["tendencia_pct"] is None and lista[ids[0]]["tiene_historial_suficiente"] is False
            assert [p["publicaciones"] for p in lista[ids[1]]["serie"]] == [100, 150] and lista[ids[1]]["tendencia_pct"] == 50.0 and lista[ids[1]]["tiene_historial_suficiente"] is True
            assert [p["publicaciones"] for p in lista[ids[2]]["serie"]] == [40]                                       # el punto de hace 90 días queda afuera de la ventana
            assert lista[ids[1]]["serie"][0]["precio_promedio"] == 1000.0 and lista[ids[1]]["serie"][0]["fecha"] == (hoy - timedelta(days=10)).strftime("%Y-%m-%d")
            raise _Revertir()
    except _Revertir:
        pass


def test_las_ventanas_de_unidades_incluyen_ambos_extremos_y_no_inventan_ventas():
    ventas = {"X": [("2026-09-01", 2), ("2026-09-05", 3), ("2026-09-09", 4)]}
    assert historial_precios.unidades_en_ventana(ventas, "X", "2026-09-01", "2026-09-09") == 9
    assert historial_precios.unidades_en_ventana(ventas, "X", "2026-09-02", "2026-09-08") == 3
    assert historial_precios.unidades_en_ventana(ventas, "Y", "2026-09-01", "2026-09-09") == 0
    assert historial_precios.ventas_diarias(None, set(), "a", "b") == {}                    # sin publicaciones no se consulta nada

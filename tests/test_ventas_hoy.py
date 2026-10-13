"""
Ventas de hoy en tres etapas (ventas_hoy.py): brutas − canceladas/devueltas = netas, con órdenes, compradores únicos, unidades y plata; y el acordeón por modelo y variante.
Números hechos a mano. La lógica de agrupar corre sola; las consultas SQL corren contra la base real dentro de una transacción que se revierte (fecha lejana: no se
mezcla con ventas de verdad).
"""
import json
import os

import pytest

import ventas_hoy
import ventas_sync


class _Revertir(Exception):
    pass


# ── La cuenta en una línea ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_frase_del_tooltip_explica_la_cuenta():
    b, c, n = ventas_hoy._bloque(7, 6, 9, 213548), ventas_hoy._bloque(2, 2, 3, 45000), ventas_hoy._bloque(5, 5, 6, 168548)
    assert ventas_hoy.frase_conciliacion(b, c, n) == "Ventas brutas: 7 órdenes ($213.548) | Canceladas/Devueltas: 2 órdenes ($45.000) | Netas: 5 órdenes ($168.548)"
    uno = ventas_hoy._bloque(1, 1, 1, 1000)
    assert ventas_hoy.frase_conciliacion(uno, ventas_hoy._bloque(), uno) == "Ventas brutas: 1 orden ($1.000) | Canceladas/Devueltas: 0 órdenes ($0) | Netas: 1 orden ($1.000)"     # singular y plural bien dichos


# ── El acordeón: modelo → variante ───────────────────────────────────────────────────────────────────────────────────────────────────

def _l(estado, orden, titulo, cantidad, precio, talle=None, etiqueta=None, familia=None):
    return {"estado": estado, "id_orden": orden, "id_meli": "MLA1", "titulo": titulo, "cantidad": cantidad, "precio": precio, "comprador": "x", "hora": "10:00", "family_id": familia, "talle": talle, "etiqueta": etiqueta}


def test_una_familia_junta_los_colores_y_los_talles_en_un_solo_modelo():
    lineas = [
        _l("neta", "A", "Buzo Manta Beige", 2, 10000, talle="M", familia="F1"),
        _l("neta", "B", "Buzo Manta Beige", 1, 10000, talle="L", familia="F1"),
        _l("neta", "C", "Buzo Manta Gris", 1, 12000, talle="M", familia="F1"),
        _l("cancelada", "D", "Buzo Manta Gris", 1, 12000, talle="M", familia="F1"),
        _l("neta", "E", "Termo 1 L", 3, 5000, etiqueta="1 L", familia="F2"),
    ]
    modelos = ventas_hoy.agrupar_por_modelo(lineas)
    assert [m["nombre"] for m in modelos] == ["Buzo Manta", "Termo 1 L"]                      # el que más facturó primero (44.000 contra 15.000)
    buzo = modelos[0]
    assert buzo["netas"] == {"ordenes": 3, "unidades": 4, "facturado": 42000.0} and buzo["canceladas"] == {"ordenes": 1, "unidades": 1, "facturado": 12000.0}
    etiquetas = {v["etiqueta"]: v for v in buzo["variantes"]}
    assert set(etiquetas) == {"Beige · M", "Beige · L", "Gris · M"}
    assert etiquetas["Beige · M"]["netas"]["unidades"] == 2 and etiquetas["Gris · M"]["netas"]["unidades"] == 1 and etiquetas["Gris · M"]["canceladas"]["unidades"] == 1
    assert buzo["variantes"][0]["etiqueta"] == "Beige · M"                                      # las variantes con más unidades primero
    assert modelos[1]["variantes"][0]["etiqueta"] == "1 L"                                     # sin talle (un termo), la variante es el atributo que la distingue


def test_un_modelo_que_solo_tuvo_canceladas_va_al_final_y_no_suma_nada_neto():
    lineas = [_l("neta", "A", "Remera Lisa", 1, 8000, talle="S", familia="R"), _l("cancelada", "B", "Campera Roja", 2, 50000, talle="M", familia="C")]
    modelos = ventas_hoy.agrupar_por_modelo(lineas)
    assert [m["nombre"] for m in modelos] == ["Remera Lisa", "Campera Roja"]
    assert modelos[1]["netas"] == {"ordenes": 0, "unidades": 0, "facturado": 0.0} and modelos[1]["canceladas"]["facturado"] == 100000.0


def test_dos_items_de_una_misma_orden_cuentan_una_sola_orden():
    lineas = [_l("neta", "A", "Buzo Manta", 1, 10000, talle="M", familia="F"), _l("neta", "A", "Buzo Manta", 1, 10000, talle="L", familia="F")]
    (modelo,) = ventas_hoy.agrupar_por_modelo(lineas)
    assert modelo["netas"] == {"ordenes": 1, "unidades": 2, "facturado": 20000.0}


def test_sin_familia_se_agrupa_por_el_titulo_sin_su_talle_y_si_no_hay_dato_la_variante_es_unica():
    lineas = [_l("neta", "A", "Termo Acero 750 ml", 1, 9000), _l("neta", "B", "Termo Acero 750 ml", 2, 9000)]
    (modelo,) = ventas_hoy.agrupar_por_modelo(lineas)
    assert modelo["nombre"] == "Termo Acero 750 ml" and [v["etiqueta"] for v in modelo["variantes"]] == ["Única"] and modelo["netas"]["unidades"] == 3


def test_un_titulo_sin_nombre_no_rompe_el_acordeon():
    (modelo,) = ventas_hoy.agrupar_por_modelo([_l("neta", "A", None, 1, 100)])
    assert modelo["nombre"] == "Sin nombre"


# ── Las consultas, contra la base real ─────────────────────────────────────────────────────────────────────────────────────────────

def _cuenta():
    import db
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def _venta(cur, cuenta, orden, id_meli, precio, cantidad, comprador, hora, fecha, id_variante=""):
    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, hora_venta, origen, comprador_nickname)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'meli', %s)""", (cuenta, orden, id_meli, id_variante, "Buzo Manta Beige", cantidad, precio, fecha, hora, comprador))


def _retirada(cur, cuenta, orden, id_meli, precio, cantidad, comprador, fecha, motivo=ventas_sync.MOTIVO_RETIRADA, id_variante=""):
    fila = {"id_orden": orden, "id_meli": id_meli, "id_variante": id_variante, "titulo": "Buzo Manta Beige", "cantidad": cantidad, "precio_venta": precio,
            "fecha_venta": fecha, "hora_venta": "11:30:00", "comprador_nickname": comprador}
    cur.execute("INSERT INTO ventas_retiradas (cuenta_id, id_orden, motivo, monto, fila) VALUES (%s, %s, %s, %s, %s::jsonb)", (cuenta, orden, motivo, precio * cantidad, json.dumps(fila)))


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_las_tres_etapas_del_dia_contra_la_base_real():
    import db
    usuario, cuenta = _cuenta()
    p, dia, otro = f"PRUEBA-HOY-{os.getpid()}", "2030-03-05", "2030-03-06"
    try:
        with db.conexion_usuario(usuario, cuenta) as c:
            cur = c.cursor()
            for n in (1, 2):                                                                                  # dos publicaciones de la misma familia; solo la 1 tiene una variante real (talle M)
                cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, family_id) VALUES (%s, %s, 'Buzo Manta Beige', %s) RETURNING id", (cuenta, f"{p}-MLA{n}", f"{p}-FAM"))
                id_padre = cur.fetchone()[0]
                cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, talle, etiqueta) VALUES (%s, %s, %s, %s, %s)",
                            (cuenta, f"{p}-V1" if n == 1 else f"{p}-MLA2_unica", id_padre, "M" if n == 1 else None, "M" if n == 1 else None))
            # NETAS de hoy: Ana compra dos ítems en UNA orden (3 unidades en total, $30.000) y Beto una (1 unidad, $12.000); la de mañana no entra
            _venta(cur, cuenta, f"{p}-A", f"{p}-MLA1", 10000, 2, "ana", "10:00:00", dia, id_variante=f"{p}-V1")
            _venta(cur, cuenta, f"{p}-A", f"{p}-MLA2", 10000, 1, "ana", "10:00:00", dia)
            _venta(cur, cuenta, f"{p}-B", f"{p}-MLA1", 12000, 1, "beto", "12:00:00", dia, id_variante=f"{p}-V1")
            _venta(cur, cuenta, f"{p}-Z", f"{p}-MLA1", 99999, 9, "zeta", "09:00:00", otro)
            # CANCELADAS de hoy: una que estaba guardada y se sacó (Ana también: sigue siendo UN comprador en las brutas), y una que nunca se contó (Carla)
            _retirada(cur, cuenta, f"{p}-C", f"{p}-MLA1", 7000, 1, "ana", dia, id_variante=f"{p}-V1")
            _retirada(cur, cuenta, f"{p}-D", f"{p}-MLA1", 5000, 2, "carla", dia, motivo=ventas_sync.MOTIVO_SIN_CONTAR, id_variante=f"{p}-V1")
            _retirada(cur, cuenta, f"{p}-D", f"{p}-MLA1", 5000, 2, "carla", dia, motivo=ventas_sync.MOTIVO_SIN_CONTAR, id_variante=f"{p}-V1")        # la misma línea archivada dos veces: cuenta una
            _retirada(cur, cuenta, f"{p}-Y", f"{p}-MLA1", 4000, 1, "yara", otro)                                                                     # cancelada de mañana: no entra

            t = ventas_hoy.totales_del_dia(cur, dia)
            assert t["netas"] == {"ordenes": 2, "compradores": 2, "unidades": 4, "facturado": 42000.0}
            assert t["canceladas"] == {"ordenes": 2, "compradores": 2, "unidades": 3, "facturado": 17000.0}                                      # 7.000 + 2×5.000
            assert t["brutas"] == {"ordenes": 4, "compradores": 3, "unidades": 7, "facturado": 59000.0}                                          # Ana en las dos etapas: 3 compradores, no 4
            assert t["brutas"]["facturado"] == t["netas"]["facturado"] + t["canceladas"]["facturado"] and t["brutas"]["unidades"] == t["netas"]["unidades"] + t["canceladas"]["unidades"]
            assert t["frase"].startswith("Ventas brutas: 4 órdenes ($59.000)")

            (modelo,) = ventas_hoy.conciliar_dia(cur, dia)["modelos"]                                          # una sola familia = un solo modelo
            assert modelo["netas"] == {"ordenes": 2, "unidades": 4, "facturado": 42000.0} and modelo["canceladas"] == {"ordenes": 2, "unidades": 3, "facturado": 17000.0}
            por_variante = {v["etiqueta"]: v for v in modelo["variantes"]}
            assert set(por_variante) == {"M", "Única"}                                                         # la 2 no tiene talle ni atributo: «Única»
            assert por_variante["M"]["netas"] == {"ordenes": 2, "unidades": 3, "facturado": 32000.0} and por_variante["M"]["canceladas"]["unidades"] == 3
            assert por_variante["Única"]["netas"] == {"ordenes": 1, "unidades": 1, "facturado": 10000.0} and por_variante["Única"]["canceladas"]["unidades"] == 0
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_un_dia_sin_nada_da_ceros_y_ningun_modelo():
    import db
    usuario, cuenta = _cuenta()
    with db.conexion_usuario(usuario, cuenta) as c:
        r = ventas_hoy.conciliar_dia(c.cursor(), "2030-03-07")
    assert r["brutas"] == r["canceladas"] == r["netas"] == ventas_hoy._bloque() and r["modelos"] == []


# ── Canceladas que el sync nunca llegó a guardar ─────────────────────────────────────────────────────────────────────────────────────

def _orden(id_, creada, items, comprador="carla"):
    return {"id": id_, "date_created": creada, "buyer": {"nickname": comprador, "first_name": "Carla"},
            "order_items": [{"item": {"id": i, "title": t, "variation_id": v}, "quantity": q, "unit_price": p} for i, t, v, q, p in items]}


def test_una_orden_cancelada_se_archiva_con_su_fecha_argentina_y_una_fila_por_item():
    # Mercado Libre informa …-04:00 aunque Argentina es UTC-3: las 23:30 de ahí son las 00:30 del día siguiente en Argentina
    orden = _orden(777, "2030-03-05T23:30:00.000-04:00", [("MLA1", "Buzo", 55, 2, 10000.5), ("MLA2", "Gorro", None, 1, 3000)])
    f1, f2 = ventas_sync._filas_de_orden_cancelada(orden)
    assert (f1["id_orden"], f1["id_meli"], f1["id_variante"], f1["cantidad"], f1["monto"]) == ("777", "MLA1", "55", 2, 20001.0)
    assert (f1["fecha_venta"], f1["hora_venta"]) == ("2030-03-06", "00:30:00") and f1["comprador_nickname"] == "carla"
    assert (f2["id_variante"], f2["monto"]) == ("", 3000.0)
    assert ventas_sync._filas_de_orden_cancelada({"id": 1, "order_items": []}) == [] and ventas_sync._filas_de_orden_cancelada({"id": 1, "date_created": "2030-03-05T10:00:00.000-04:00"}) == []


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma al salir: así lo que escribe el sync se revierte al final de la prueba."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_el_sync_retira_las_que_contaban_y_archiva_aparte_las_que_nunca_contaron(monkeypatch):
    import db
    usuario, cuenta = _cuenta()
    p, dia = f"PRUEBA-CANC-{os.getpid()}", "2030-03-05"
    contaba = _orden(f"{p}-1", "2030-03-05T10:00:00.000-04:00", [(f"{p}-MLA1", "Buzo", None, 1, 10000)], comprador="ana")
    nunca = _orden(f"{p}-2", "2030-03-05T11:00:00.000-04:00", [(f"{p}-MLA1", "Buzo", None, 3, 4000)], comprador="beto")
    monkeypatch.setattr(ventas_sync, "_ordenes_canceladas", lambda *a, **k: [contaba, nunca])
    try:
        with db.conexion_usuario(usuario, cuenta) as conexion:
            monkeypatch.setattr(ventas_sync.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            cur = conexion.cursor()
            _venta(cur, cuenta, f"{p}-1", f"{p}-MLA1", 10000, 1, "ana", "10:00:00", dia)                       # estaba guardada y sumaba
            assert ventas_sync.retirar_ventas_canceladas(usuario, cuenta, "tok", 99) == 1                      # retiró una fila de `ventas`
            cur.execute("SELECT id_orden, motivo, monto FROM ventas_retiradas WHERE id_orden LIKE %s ORDER BY id_orden", (f"{p}-%",))
            assert cur.fetchall() == [(f"{p}-1", "cancelada", 10000), (f"{p}-2", "cancelada_sin_contar", 12000)]
            cur.execute("SELECT COUNT(*) FROM ventas WHERE id_orden LIKE %s", (f"{p}-%",))
            assert cur.fetchone()[0] == 0                                                                      # ninguna de las dos sigue en `ventas`
            assert ventas_sync.retirar_ventas_canceladas(usuario, cuenta, "tok", 99) == 0                      # la próxima vez no duplica nada
            cur.execute("SELECT COUNT(*) FROM ventas_retiradas WHERE id_orden LIKE %s", (f"{p}-%",))
            assert cur.fetchone()[0] == 2
            t = ventas_hoy.totales_del_dia(cur, dia)
            assert (t["brutas"]["ordenes"], t["canceladas"]["ordenes"], t["netas"]["ordenes"]) == (2, 2, 0) and t["canceladas"]["unidades"] == 4
            raise _Revertir()
    except _Revertir:
        pass


def test_ganancia_real_solo_descuenta_las_canceladas_que_alguna_vez_contaron():
    """«Ventas reembolsadas» de Ganancia Real cuenta lo que se sacó de la facturación: una orden que nunca contó no puede restar nada."""
    fuente = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metricas.py"), encoding="utf-8").read()
    assert "FROM ventas_retiradas WHERE motivo = 'cancelada' AND" in fuente


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_la_api_de_hoy_trae_la_conciliacion_y_sus_numeros_coinciden_con_los_de_siempre():
    """`/api/hoy` sigue dando facturado/unidades/órdenes de hoy (los lee el chat de IA) y esos números SON las netas de la conciliación."""
    import dashboard
    usuario, cuenta = _cuenta()
    r = dashboard.obtener_ventas_hoy(usuario, cuenta)
    c = r["conciliacion"]
    assert r["ordenes_hoy"] == c["netas"]["ordenes"] and r["unidades_hoy"] == c["netas"]["unidades"]
    assert r["facturado_hoy"] == dashboard.formatear_moneda(c["netas"]["facturado"])
    assert c["brutas"]["facturado"] == round(c["netas"]["facturado"] + c["canceladas"]["facturado"], 2)
    assert c["brutas"]["unidades"] == c["netas"]["unidades"] + c["canceladas"]["unidades"] and c["brutas"]["ordenes"] == c["netas"]["ordenes"] + c["canceladas"]["ordenes"]
    assert sum(m["netas"]["unidades"] for m in c["modelos"]) == c["netas"]["unidades"] and sum(m["canceladas"]["unidades"] for m in c["modelos"]) == c["canceladas"]["unidades"]

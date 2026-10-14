"""
Las herramientas de lectura que se sumaron al asistente: ganancia por modelo, publicidad, precios, comparar períodos, reputación, Monotributo y búsqueda de un producto.
Los números se calculan a mano (no se «captura» lo que devuelve el código). Lo que viene de Mercado Libre se simula; lo de la base se prueba con datos de prueba dentro de una transacción que se revierte.
"""
import json
import os
from datetime import date

import pytest

import asistente_herramientas as herr

CON_BASE = pytest.mark.skipif(not (os.getenv("DATABASE_URL") and os.getenv("DATABASE_URL_ADMIN")), reason="Sin DATABASE_URL/DATABASE_URL_ADMIN")
HOY = date(2030, 3, 20)


def _ctx(hoy=HOY):
    return herr.Contexto(1, 1, hoy)


class _Prestada:
    """Entrega una conexión ya abierta y NO confirma: lo que se escriba en la prueba se revierte."""
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


class _Revertir(Exception):
    pass


# ── Registro ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_las_herramientas_nuevas_estan_registradas_con_su_descripcion():
    for nombre in ("ganancia_por_modelo", "publicidad", "precios", "comparar_periodos", "reputacion", "monotributo", "producto"):
        h = herr.HERRAMIENTAS[nombre]
        assert len(h["descripcion"]) > 40 and callable(h["funcion"]), nombre
    assert {d["function"]["name"] for d in herr.definiciones()} >= {"ganancia_por_modelo", "publicidad", "precios", "comparar_periodos", "reputacion", "monotributo", "producto"}


# ── Ganancia por modelo ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _modelo(titulo, unidades, facturado, neto_total, costo_u=100.0):
    return {"titulo": titulo, "unidades": unidades, "raw": {"total_facturado": facturado, "neto_total": neto_total, "neto_u": round(neto_total / unidades, 2) if unidades else 0, "costo_u": costo_u}}


def test_ganancia_por_modelo_ordena_por_plata_que_deja_y_separa_los_que_pierden(monkeypatch):
    modelos = [_modelo("Campera A", 10, 100000, 30000), _modelo("Termo B", 5, 50000, -2000), _modelo("Buzo C", 20, 80000, 24000, costo_u=0), _modelo("Taza D", 4, 8000, -500)]
    monkeypatch.setattr(herr, "_calcular_ganancia", lambda ctx, d, h: {"consolidados": modelos, "ads_incompleto": False})
    d = herr.ejecutar("ganancia_por_modelo", json.dumps({"dias": 30}), _ctx())["datos"]
    assert [m["modelo"] for m in d["los_que_mas_dejan"]] == ["Campera A", "Buzo C", "Taza D", "Termo B"]       # por plata que dejan, de más a menos
    assert [m["modelo"] for m in d["los_que_pierden_plata"]] == ["Termo B", "Taza D"]                         # la mayor pérdida primero
    assert d["los_que_mas_dejan"][0]["margen_pct"] == 30.0 and d["los_que_pierden_plata"][0]["margen_pct"] == -4.0
    assert d["modelos_sin_costo_de_fabricacion_cargado"] == ["Buzo C"] and "inflada" not in d.get("aviso_publicidad", "") and "más alta que la real" in d["aviso"]
    assert d["desde"] == "2030-02-19" and d["hasta"] == "2030-03-20" and d["modelos_vendidos"] == 4
    assert "cargos mensuales" in d["aclaracion"]                                                               # la suma de los modelos no incluye los cargos mensuales: se dice


def test_ganancia_por_modelo_avisa_si_falto_la_publicidad_y_no_inventa_margen_sin_ventas(monkeypatch):
    monkeypatch.setattr(herr, "_calcular_ganancia", lambda ctx, d, h: {"consolidados": [_modelo("Raro", 0, 0, 0)], "ads_incompleto": True})
    d = herr.ejecutar("ganancia_por_modelo", "{}", _ctx())["datos"]
    assert d["los_que_mas_dejan"][0]["margen_pct"] is None and "publicidad" in d["aviso_publicidad"]
    monkeypatch.setattr(herr, "_calcular_ganancia", lambda ctx, d, h: {})
    assert herr.ejecutar("ganancia_por_modelo", "{}", _ctx())["datos"]["modelos_vendidos"] == 0


def test_la_ganancia_real_avisa_si_la_publicidad_vino_incompleta(monkeypatch):
    class _Cursor:
        def execute(self, *a, **k):
            pass

        def close(self):
            pass

    class _Conexion:
        def cursor(self):
            return _Cursor()
    monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(_Conexion()))
    monkeypatch.setattr(herr.costos_mod, "cobertura_de_costos", lambda cursor, d, h: {"facturado": 1000, "sin_costo": 0, "pct_sin_costo": 0.0, "publicaciones": 0, "avisar": False})
    monkeypatch.setattr(herr, "_calcular_ganancia", lambda ctx, d, h: {"ads_incompleto": True, "resumen": {"raw": {"facturado": 1000, "ganancia_neta": 100}}})
    assert "publicidad" in herr.ejecutar("ganancia_real", "{}", _ctx())["datos"]["aviso"]


# ── Publicidad ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _datos_de_publicidad(**cambios):
    base = {
        "campanas": [
            {"nombre": "Campaña A", "estado": "active", "costo": 1000.0, "ventas_atribuidas": 9000.0, "roas": 9.0, "unidades": 8, "pct_presupuesto": 95.0, "presupuesto": 100.0,
             "recomendacion": {"tipo": "oportunidad", "texto": "Subile el presupuesto."}},
            {"nombre": "Campaña B", "estado": "paused", "costo": 500.0, "ventas_atribuidas": 600.0, "roas": 1.2, "unidades": 1, "pct_presupuesto": None, "presupuesto": None, "recomendacion": None},
        ],
        "unidades_total": 9, "roas_general": 6.0, "roas_equilibrio": 2.5, "te_deja_ganancia": True, "acos_general": 16.7, "tacos": 8.0, "cpc": 120.0, "cpa": 166.67, "pct_origen_pagado": 70.0,
        "anterior": {"costo_pct": 10.0, "ventas_pct": 25.0, "roas": 5.0, "roas_diff": 1.0},
        "items_ads": [{"titulo": "Termo X", "costo": 300.0, "sin_ventas": True}, {"titulo": "Taza Y", "costo": 200.0, "sin_ventas": True}, {"titulo": "Buzo Z", "costo": 1000.0, "sin_ventas": False}],
        "incompleto": False,
    }
    base.update(cambios)
    return base


def test_publicidad_resume_lo_que_muestra_la_pantalla(monkeypatch):
    monkeypatch.setattr(herr, "_token", lambda ctx: "token")
    monkeypatch.setattr(herr.publicidad_mod, "calcular_datos_publicidad", lambda u, c, t, d, h: _datos_de_publicidad())
    d = herr.ejecutar("publicidad", json.dumps({"dias": 14}), _ctx())["datos"]
    assert d["gastaste"] == 1500.0 and d["ventas_que_trajo_la_publicidad"] == 9600.0 and d["retorno_roas"] == 6.0 and d["roas_de_equilibrio"] == 2.5 and d["la_publicidad_te_deja_ganancia"] is True
    assert d["desde"] == "2030-03-07" and d["hasta"] == "2030-03-20"
    assert d["veces_por_encima_del_equilibrio"] == 2.4                                                         # 6,0 ÷ 2,5
    assert d["campanas"][0] == {"campana": "Campaña A", "estado": "active", "gastaste": 1000.0, "ventas": 9000.0, "retorno_roas": 9.0, "unidades": 8, "presupuesto_diario": 100.0,
                                "uso_promedio_del_presupuesto_diario_pct": 95.0, "sugerencia": "Subile el presupuesto."}
    assert d["campanas"][1]["presupuesto_diario"] is None and d["campanas"][1]["sugerencia"] is None
    assert d["publicaciones_que_gastaron_sin_vender"] == {"cantidad": 2, "gastaste_en_ellas": 500.0, "las_que_mas_gastaron": [{"publicacion": "Termo X", "gastaste": 300.0}, {"publicacion": "Taza Y", "gastaste": 200.0}]}
    assert d["contra_el_periodo_anterior"] == {"variacion_del_gasto_pct": 10.0, "variacion_de_las_ventas_pct": 25.0, "roas_anterior": 5.0}


def test_publicidad_sin_product_ads_o_sin_respuesta_de_mercado_libre_no_inventa_ceros(monkeypatch):
    monkeypatch.setattr(herr, "_token", lambda ctx: "token")
    monkeypatch.setattr(herr.publicidad_mod, "calcular_datos_publicidad", lambda *a: None)
    d = herr.ejecutar("publicidad", "{}", _ctx())["datos"]
    assert d["usa_product_ads"] is False and "gastaste" not in d
    monkeypatch.setattr(herr.publicidad_mod, "calcular_datos_publicidad", lambda *a: _datos_de_publicidad(incompleto=True, campanas=[]))
    r = herr.ejecutar("publicidad", "{}", _ctx())
    assert r["ok"] is False and "no puedo decir cuánto" in r["error"]                                         # un error de Mercado Libre no se cuenta como «no gastaste nada»


def test_la_pantalla_de_publicidad_distingue_un_error_de_mercado_libre_de_cero_gasto():
    fuente = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "publicidad.py"), encoding="utf-8").read()
    assert "estricto=True" in fuente and '"incompleto": incompleto' in fuente


def test_el_presupuesto_de_una_campana_es_diario_y_se_compara_con_todos_los_dias_del_periodo():
    """Se verificó con la cuenta real: una campaña con $38.159 de presupuesto gasta $38.159 cada día. Dividir el gasto de 30 días por el presupuesto de un día daba «2704 % usado»."""
    from publicidad import uso_del_presupuesto
    assert uso_del_presupuesto(1_144_770, 38_159, 30) == 100.0                                                 # gasta todo el presupuesto todos los días
    assert uso_del_presupuesto(572_385, 38_159, 30) == 50.0                                                    # la mitad
    assert uso_del_presupuesto(38_159, 38_159, 1) == 100.0                                                     # un solo día
    assert uso_del_presupuesto(500, None, 14) is None and uso_del_presupuesto(500, 0, 14) is None and uso_del_presupuesto(500, 100, 0) is None
    assert uso_del_presupuesto(None, 100, 5) == 0.0


# ── Comparar períodos ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_los_periodos_a_comparar():
    ctx = _ctx()
    assert herr._periodos_a_comparar(ctx, 10, "dias")[:2] == ((date(2030, 3, 11), date(2030, 3, 20)), (date(2030, 3, 1), date(2030, 3, 10)))        # 10 días contra los 10 anteriores
    assert herr._periodos_a_comparar(ctx, None, "dias")[:2] == ((date(2030, 2, 19), date(2030, 3, 20)), (date(2030, 1, 20), date(2030, 2, 18)))      # por defecto 30
    assert herr._periodos_a_comparar(ctx, None, "mes")[:2] == ((date(2030, 3, 1), date(2030, 3, 20)), (date(2030, 2, 1), date(2030, 2, 20)))         # lo que va del mes contra el mismo tramo del anterior
    assert herr._periodos_a_comparar(_ctx(date(2030, 3, 31)), None, "mes")[:2] == ((date(2030, 3, 1), date(2030, 3, 31)), (date(2030, 2, 1), date(2030, 2, 28)))   # febrero no tiene 31 días
    assert herr._periodos_a_comparar(_ctx(date(2030, 3, 1)), None, "mes")[:2] == ((date(2030, 3, 1), date(2030, 3, 1)), (date(2030, 2, 1), date(2030, 2, 1)))
    assert herr._periodos_a_comparar(_ctx(date(2030, 1, 15)), None, "mes")[1] == (date(2029, 12, 1), date(2029, 12, 15))                              # cruce de año


def test_la_variacion_no_inventa_porcentajes_sin_base():
    assert herr._variacion(150, 100) == {"actual": 150.0, "anterior": 100.0, "diferencia": 50.0, "variacion_pct": 50.0}
    assert herr._variacion(50, 100)["variacion_pct"] == -50.0
    assert herr._variacion(10, 0)["variacion_pct"] is None and herr._variacion(0, 0)["diferencia"] == 0.0 and herr._variacion(None, None)["actual"] == 0.0


def _raw(facturado, ganancia, comision, envios, ads, fabricacion):
    return {"resumen": {"raw": {"facturado": facturado, "ganancia_neta": ganancia, "comision": comision, "envios": envios, "costo_ads": ads, "costo_fabricacion": fabricacion}}}


@CON_BASE
def test_comparar_periodos_suma_las_ventas_de_cada_periodo_y_calcula_las_diferencias(monkeypatch):
    import db
    pid = os.getpid() % 100000
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id, usuario_id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta, usuario = cur.fetchone()
            monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            filas = [(f"CMP-A{k}-{pid}", date(2030, 3, 12 + k), 2, 2000) for k in range(5)] + [(f"CMP-B{k}-{pid}", date(2030, 3, 2 + k), 1, 1000) for k in range(3)]     # 5 órdenes (10 u, $20.000) y 3 órdenes (3 u, $3.000)
            for orden, fecha, cantidad, precio in filas:
                cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen)
                               VALUES (%s, %s, 'MLA-CMP', 'V-CMP', 'Termo Prueba', %s, %s, %s, 'meli')""", (cuenta, orden, cantidad, precio, fecha))
            monkeypatch.setattr(herr, "_calcular_ganancia", lambda ctx, desde, hasta: _raw(20000, 6000, 3000, 1000, 2000, 8000) if desde == date(2030, 3, 11) else _raw(3000, 600, 450, 300, 450, 1200))
            ctx = herr.Contexto(usuario, cuenta, HOY)
            d = herr.ejecutar("comparar_periodos", json.dumps({"dias": 10}), ctx)["datos"]
            assert d["periodo_actual"] == {"desde": "2030-03-11", "hasta": "2030-03-20"} and d["periodo_anterior"] == {"desde": "2030-03-01", "hasta": "2030-03-10"}
            assert d["facturado"] == {"actual": 20000.0, "anterior": 3000.0, "diferencia": 17000.0, "variacion_pct": 566.7}
            assert d["unidades"]["actual"] == 10 and d["unidades"]["anterior"] == 3 and d["ordenes"]["actual"] == 5 and d["ordenes"]["anterior"] == 3
            assert d["ganancia_neta_real"] == {"actual": 6000.0, "anterior": 600.0, "diferencia": 5400.0, "variacion_pct": 900.0}
            assert d["margen_pct"] == {"actual": 30.0, "anterior": 20.0, "diferencia_en_puntos": 10.0}
            assert d["costos"]["publicidad"] == {"actual": 2000.0, "anterior": 450.0, "diferencia": 1550.0, "variacion_pct": 344.4}
            assert set(d["costos"]) == {"cargos_de_mercado_libre", "envios", "publicidad", "costo_de_fabricacion"}
            json.dumps(d)

            def _falla(ctx, desde, hasta):
                raise herr.ErrorDeHerramienta("La cuenta de Mercado Libre está desconectada")
            monkeypatch.setattr(herr, "_calcular_ganancia", _falla)
            d = herr.ejecutar("comparar_periodos", json.dumps({"dias": 10}), ctx)["datos"]
            assert d["facturado"]["actual"] == 20000.0 and "desconectada" in d["ganancia_no_disponible"] and "ganancia_neta_real" not in d      # las ventas se comparan igual

            def _rota(ctx, desde, hasta):
                raise RuntimeError("detalle interno")
            monkeypatch.setattr(herr, "_calcular_ganancia", _rota)
            d = herr.ejecutar("comparar_periodos", json.dumps({"dias": 10}), ctx)["datos"]
            assert "detalle interno" not in json.dumps(d) and "ganancia_no_disponible" in d
            raise _Revertir()
    except _Revertir:
        pass


# ── Reputación y Monotributo ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_la_reputacion_pasa_las_tasas_a_porcentaje_y_no_inventa_si_mercado_libre_no_contesta(monkeypatch):
    class _Cursor:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return (555,)

        def close(self):
            pass

    class _Conexion:
        def cursor(self):
            return _Cursor()
    monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(_Conexion()))
    monkeypatch.setattr(herr, "_token", lambda ctx: "token")
    pedidos = []
    rep = {"nivel_nombre": "Excelente (verde)", "power_seller_nombre": "Gold", "total_transacciones": 100, "completadas": 90, "canceladas": 10,
           "reclamos": {"tasa": 0.0123, "valor": 1}, "demora_en_despacho": {"tasa": 0.04, "valor": 4}, "cancelaciones_metrica": {"tasa": None, "valor": None}}
    monkeypatch.setattr(herr.reputacion_mod, "obtener_reputacion", lambda token, user_id: pedidos.append(user_id) or rep)
    d = herr.ejecutar("reputacion", "{}", _ctx())["datos"]
    assert pedidos == [555] and d["nivel"] == "Excelente (verde)" and d["mercadolider"] == "Gold"
    assert d["metricas_que_arman_el_nivel_pct"] == {"reclamos": 1.23, "demora_en_el_despacho": 4.0, "cancelaciones": None}
    monkeypatch.setattr(herr.reputacion_mod, "obtener_reputacion", lambda *a: None)
    r = herr.ejecutar("reputacion", "{}", _ctx())
    assert r["ok"] is False and "no devolvió la reputación" in r["error"]


def test_monotributo_solo_se_calcula_si_la_persona_declaro_que_es_monotributista(monkeypatch):
    llamadas = []
    monkeypatch.setattr(herr.monotributo_mod, "evaluar_categoria", lambda u, c: llamadas.append(1) or {})
    for condicion in (None, herr.fiscal.RESPONSABLE_INSCRIPTO, herr.fiscal.SIN_INSCRIPCION):
        monkeypatch.setattr(herr.fiscal, "obtener", lambda u, c, valor=condicion: valor)
        d = herr.ejecutar("monotributo", "{}", _ctx())["datos"]
        assert d["aplica"] is False and "contador" in d["mensaje"]
    assert llamadas == []                                                                                      # nunca se supone la condición fiscal


def test_monotributo_para_un_monotributista_resume_el_tope_y_pide_confirmar_con_un_contador(monkeypatch):
    monkeypatch.setattr(herr.fiscal, "obtener", lambda u, c: herr.fiscal.MONOTRIBUTO)
    monkeypatch.setattr(herr.monotributo_mod, "evaluar_categoria", lambda u, c: {
        "facturacion_12m": 40000000.0, "categoria_real": "F", "categoria_declarada": "F", "cuota_mensual_declarada": 200000.0, "tope_categoria_declarada": 80000000.0,
        "variacion_pct_propia": 12.5, "meses_para_cruzar": 8.0, "alertas": [{"tipo": "importante", "texto": "Usás el 50 % del techo."}], "vigente_desde": "2026-08-01"})
    d = herr.ejecutar("monotributo", "{}", _ctx())["datos"]
    assert d["te_queda_para_llegar_al_tope"] == 40000000.0                                                     # 80.000.000 − 40.000.000
    assert d["aplica"] is True and d["porcentaje_del_tope_usado"] == 50.0 and d["avisos"] == ["Usás el 50 % del techo."] and "contador" in d["aclaracion"]
    assert d["tope_anual_de_la_categoria_declarada"] == 80000000.0 and d["escalas_vigentes_desde"] == "2026-08-01"
    monkeypatch.setattr(herr.monotributo_mod, "evaluar_categoria", lambda u, c: {
        "facturacion_12m": 1.0, "categoria_real": "A", "categoria_declarada": None, "cuota_mensual_declarada": None, "tope_categoria_declarada": None,
        "variacion_pct_propia": None, "meses_para_cruzar": None, "alertas": [], "vigente_desde": "2026-08-01"})
    d = herr.ejecutar("monotributo", "{}", _ctx())["datos"]
    assert d["porcentaje_del_tope_usado"] is None and d["tope_anual_de_la_categoria_declarada"] is None and d["te_queda_para_llegar_al_tope"] is None     # sin categoría declarada no se inventa un tope


# ── Buscar un producto ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_las_palabras_de_busqueda_se_limpian_y_se_acotan():
    assert herr._palabras_de_busqueda("Térmo  Acero-Inoxidable, 1L!") == ["termo", "acero", "inoxidable", "1l"]
    assert herr._palabras_de_busqueda("a b campera") == ["campera"]                                            # una sola letra no busca nada
    assert len(herr._palabras_de_busqueda("uno dos tres cuatro cinco seis siete ocho")) == herr.MAX_PALABRAS_DE_BUSQUEDA
    assert herr._palabras_de_busqueda("x" * 500) == ["x" * herr.MAX_LARGO_DE_BUSQUEDA]
    for vacio in (None, "", "   ", "%", "'", "a", "_ _"):
        with pytest.raises(herr.ErrorDeHerramienta):
            herr._palabras_de_busqueda(vacio)


@CON_BASE
def test_producto_y_precios_con_datos_de_prueba(monkeypatch):
    import db
    pid = os.getpid() % 100000
    marca = f"tstzz{pid}"
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id, usuario_id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta, usuario = cur.fetchone()
            monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))

            def _padre(id_meli, titulo, estado, precio, costo, familia, calidad=None, visitas=0, previas=0, op_prom=None, op_total=0):
                cur.execute("""INSERT INTO productos_padre (cuenta_id, id_meli, titulo, estado, precio, precio_costo, family_id, calidad_score, visitas_14d, visitas_previas_14d, opiniones_promedio, opiniones_total)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""", (cuenta, id_meli, titulo, estado, precio, costo, familia, calidad, visitas, previas, op_prom, op_total))
                return cur.fetchone()[0]

            def _variante(id_padre, id_variante, propio, full):
                cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, talle, color, stock_propio, stock_full) VALUES (%s, %s, %s, 'Único', 'Único', %s, %s)",
                            (cuenta, id_variante, id_padre, propio, full))

            def _venta(id_meli, n, cantidad, precio, cargo, envio, fecha=date(2030, 3, 10)):
                for k in range(n):
                    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, origen)
                                   VALUES (%s, %s, %s, '', 'x', %s, %s, %s, %s, %s, 'meli')""", (cuenta, f"{id_meli}-{k}", id_meli, cantidad, precio, cargo, envio, fecha))

            # Un modelo con dos colores (una publicación activa y otra pausada), a $10.000 con costo $4.000; 3 ventas de 1 unidad con 15 % de cargos y $500 de envío
            p1 = _padre(f"{marca}-1", f"Termo {marca} Acero Negro", "active", 10000, 4000, f"FAM-{marca}", calidad=80, visitas=100, previas=50, op_prom=4.5, op_total=10)
            _padre(f"{marca}-2", f"Termo {marca} Acero Rojo", "paused", 11000, 0, f"FAM-{marca}")
            _variante(p1, f"{marca}-1-A", 3, 2)
            _variante(p1, f"{marca}-1-B", 0, 0)
            _venta(f"{marca}-1", 3, 1, 10000, 1500, 500)
            # Otra publicación, por debajo de su precio mínimo: $4.000 con costo $4.000
            _padre(f"{marca}-3", f"Taza {marca} Barata", "active", 4000, 4000, f"FAM-{marca}-3")
            _venta(f"{marca}-3", 3, 1, 4000, 600, 500)

            ctx = herr.Contexto(usuario, cuenta, HOY)
            d = herr.ejecutar("producto", json.dumps({"buscar": f"térmo {marca}"}), ctx)["datos"]                  # con acento y en otro orden: igual lo encuentra
            assert d["coincidencias"] == 2 and len(d["productos"]) == 1 and d["hay_mas_productos"] == 0
            p = d["productos"][0]
            assert p["producto"] == f"Termo {marca} Acero" and p["publicaciones_activas"] == 1 and p["publicaciones_pausadas"] == 1
            assert p["precio"] == {"minimo": 10000.0, "maximo": 10000.0} and p["publicaciones_activas_sin_costo_de_fabricacion_cargado"] == 0     # la pausada sin costo no cuenta
            assert p["stock"] == {"unidades": 5, "variantes_activas_sin_stock": 1}
            assert p["ultimos_30_dias"] == {"unidades_vendidas": 3, "facturado": 30000.0}
            assert p["margen_actual_pct"] == 40.0                                                                 # (10.000 × 0,85 − 500 − 4.000) ÷ 10.000
            assert p["estado_del_precio"] == {"pierden_plata": 0, "ganan_menos_que_tu_margen_objetivo": 0, "cubren_tu_margen": 1}
            assert p["calidad_promedio_de_mercado_libre"] == 80.0 and p["visitas_14_dias"] == 100 and p["variacion_de_visitas_pct"] == 100.0
            assert p["opiniones"] == {"promedio": 4.5, "cantidad": 10}
            json.dumps(d)

            assert herr.ejecutar("producto", json.dumps({"buscar": "'; DROP TABLE ventas; --"}), ctx)["datos"]["coincidencias"] == 0       # es texto, nunca SQL
            assert herr.ejecutar("producto", json.dumps({"buscar": f"{marca}zz"}), ctx)["datos"]["coincidencias"] == 0
            assert "mensaje" in herr.ejecutar("producto", json.dumps({"buscar": f"{marca}zz"}), ctx)["datos"]
            assert herr.ejecutar("producto", json.dumps({"buscar": ""}), ctx)["ok"] is False

            pr = herr.ejecutar("precios", json.dumps({"margen_objetivo": 20}), ctx)["datos"]
            peor = next(i for i in pr["pierden_plata_al_precio_actual"]["las_peores"] if marca in i["publicacion"])
            # neto = 4.000 × 0,85 − 500 − 4.000 = −1.100 por unidad; mínimo = (4.000 + 500) ÷ 0,85 = 5.294 → $5.300; pierde 1.100 × 3 ventas ÷ (90 ÷ 30) = 1.100 por mes
            assert peor["precio_actual"] == 4000.0 and peor["margen_actual_pct"] == -27.5 and peor["precio_minimo"] == 5300 and peor["perdida_mensual_estimada"] == 1100.0 and peor["unidades_vendidas_90_dias"] == 3
            assert pr["margen_objetivo_pct"] == 20.0 and pr["pierden_plata_al_precio_actual"]["cantidad"] >= 1
            assert herr.ejecutar("precios", json.dumps({"margen_objetivo": 999}), ctx)["datos"]["margen_objetivo_pct"] == 60.0       # se acota
            assert herr.ejecutar("precios", json.dumps({"margen_objetivo": "mucho"}), ctx)["datos"]["margen_objetivo_pct"] == 20.0   # y un valor raro vuelve al de siempre
            json.dumps(pr)
            raise _Revertir()
    except _Revertir:
        pass


@CON_BASE
def test_producto_muestra_solo_tres_modelos_y_avisa_que_hay_mas(monkeypatch):
    import db
    marca = f"tstzy{os.getpid() % 100000}"
    try:
        with db.conexion_admin() as conexion:
            cur = conexion.cursor()
            cur.execute("SELECT id, usuario_id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta, usuario = cur.fetchone()
            monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            for i, nombre in enumerate(("Alfa", "Beta", "Gamma", "Delta")):
                cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, estado, precio, precio_costo, family_id) VALUES (%s, %s, %s, 'active', 1000, 400, %s)",
                            (cuenta, f"{marca}-{i}", f"Producto {marca} {nombre}", f"FAM-{marca}-{i}"))
                for k in range(i):                                                                             # Alfa 0 ventas, Beta 1, Gamma 2, Delta 3
                    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, fecha_venta, origen)
                                   VALUES (%s, %s, %s, '', 'x', 1, 1000, '2030-03-10', 'meli')""", (cuenta, f"{marca}-{i}-{k}", f"{marca}-{i}"))
            d = herr.ejecutar("producto", json.dumps({"buscar": marca}), herr.Contexto(usuario, cuenta, HOY))["datos"]
            assert d["coincidencias"] == 4 and d["hay_mas_productos"] == 1
            assert [p["producto"].split()[-1] for p in d["productos"]] == ["Delta", "Gamma", "Beta"]            # los más vendidos primero
            raise _Revertir()
    except _Revertir:
        pass

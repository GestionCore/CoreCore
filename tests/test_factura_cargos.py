"""
La factura de Mercado Libre: cómo se agrupan los cargos, qué cargos mensuales se descuentan de la ganancia y cómo se reparten por día. Funciones puras, sin base ni red.
Los montos de los ejemplos son los de una factura real (período 09/09–08/10), redondeados.
"""
from datetime import date

import facturacion as f


def _cargo(tipo, monto, grupo="", etiqueta=None):
    return {"type": tipo, "label": etiqueta or tipo, "group_description": grupo, "amount": monto}


def _factura(cargos, bonos=()):
    return {"bill_includes": {"charges": list(cargos), "bonuses": list(bonos)}}


FACTURA = _factura(
    [_cargo("CVFV", 2000.0, "Cargos por venta\t"), _cargo("CFF", 1500.0, "Cargos por envíos", "Cargo por Mercado Envíos"),
     _cargo("CDS", 100.0, "Cargos por envíos", "Cargo por Mercado Envíos"), _cargo("CDSD", 90.0, "Cargos por envíos", "Cargo por devolución"),
     _cargo("PADS", 1300.0, "Publicidad", "Campañas de publicidad - Product Ads"),
     _cargo("CFWA", 25.0, "Cargos de envíos full", "Cargo por servicio de almacenamiento Full"),
     _cargo("CESM", 150.0, "Cargos de eShop", "Cargo de mantenimiento de eShop"), _cargo("CSTP", 270.0, "Cargos de Reputación"),
     _cargo("IIBB", 60.0, "Impuestos", "Percepción impuesto IIBB")],
    [{"type": "BVFV", "label": "BVFV", "group_description": "Bonificaciones", "amount": -250.0},
     {"type": "BFF", "label": "Bonificación cargo por Mercado Envíos", "group_description": "Bonificaciones", "amount": -180.0},
     {"type": "BDSD", "label": "Anulación del cargo por devolución", "group_description": "Bonificaciones", "amount": -90.0}],
)


# ── Qué grupo es cada cargo ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_almacenamiento_de_full_no_es_un_envio_aunque_mercado_libre_lo_agrupe_asi():
    assert f.grupo_de_cargo("CFWA", "Cargos de envíos full") == "full"
    assert f.grupo_de_cargo("CFRS", "Cargos de envíos full") == "full"
    assert f.grupo_de_cargo("CFF", "Cargos por envíos") == "envios"
    assert f.grupo_de_cargo("CDSD", "Cargos por envíos") == "envios"


def test_el_grupo_con_tabulador_final_de_mercado_libre_se_reconoce():
    assert f.grupo_de_cargo("CVFV", "Cargos por venta\t") == "ventas"
    assert f.grupo_de_cargo("XYZ", "Cargos por venta\t") == "ventas"           # un código nuevo cae en su grupo por el nombre


def test_publicidad_impuestos_y_otros():
    assert f.grupo_de_cargo("PADS", "Publicidad") == "publicidad"
    assert f.grupo_de_cargo("IIBBME", "Impuestos") == "impuestos"
    assert f.grupo_de_cargo("CBTUPP", "Percepciones Impositivas Mercado Pago") == "impuestos"
    assert f.grupo_de_cargo("CESM", "Cargos de eShop") == "otros"
    assert f.grupo_de_cargo("QQQ", "") == "otros"


# ── La factura agrupada ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_la_factura_agrupada_suma_lo_mismo_que_la_factura():
    a = f.agrupar_factura(FACTURA)
    bruto = 2000 + 1500 + 100 + 90 + 1300 + 25 + 150 + 270 + 60
    bonos = -250 - 180 - 90
    assert a["total_factura"] == bruto + bonos == a["total"]
    assert round(sum(fila["monto"] for fila in a["filas"]), 2) == a["total"]


def test_el_envio_suma_full_y_correo_y_las_bonificaciones_van_al_final():
    a = f.agrupar_factura(FACTURA)
    claves = [fila["clave"] for fila in a["filas"]]
    assert claves[-1] == "bonificaciones" and set(claves) == {"ventas", "envios", "publicidad", "full", "otros", "impuestos", "bonificaciones"}
    envios = next(x for x in a["filas"] if x["clave"] == "envios")
    assert envios["monto"] == 1500 + 100 + 90
    assert {d["label"] for d in envios["detalle"]} == {"Cargo por Mercado Envíos", "Cargo por devolución"}       # CFF y CDS tienen el mismo nombre: una sola línea
    full = next(x for x in a["filas"] if x["clave"] == "full")
    assert full["monto"] == 25 and full["label"].startswith("Servicios de FULL")


def test_los_codigos_sin_nombre_se_muestran_con_uno_legible():
    a = f.agrupar_factura(FACTURA)
    otros = next(x for x in a["filas"] if x["clave"] == "otros")
    assert {d["label"] for d in otros["detalle"]} == {"Cargo de mantenimiento de eShop", "Cargo de reputación"}
    bonos = next(x for x in a["filas"] if x["clave"] == "bonificaciones")
    assert "Bonificación de cargos por venta" in {d["label"] for d in bonos["detalle"]}


def test_flex_suma_su_costo_bruto_al_envio_y_su_reintegro_a_las_bonificaciones_sin_cambiar_lo_que_cuestan_los_envios():
    sin = f.agrupar_factura(FACTURA)
    con = f.agrupar_factura(FACTURA, flex_neto=900.0, flex_reintegro=0.10)           # neto 900 = bruto 1000 menos el 10 %
    envios = next(x for x in con["filas"] if x["clave"] == "envios")
    bonos = next(x for x in con["filas"] if x["clave"] == "bonificaciones")
    assert envios["monto"] == next(x for x in sin["filas"] if x["clave"] == "envios")["monto"] + 1000.0
    assert bonos["monto"] == next(x for x in sin["filas"] if x["clave"] == "bonificaciones")["monto"] - 100.0
    assert con["total_factura"] == sin["total_factura"]                              # la factura de Mercado Libre no cambia
    assert con["total"] == sin["total"] + 900.0                                      # y el total suma solo lo que de verdad cuesta Flex
    flex = next(d for d in envios["detalle"] if d["label"].startswith("Envíos Flex"))
    assert flex["monto"] == 1000.0 and "no figura en la factura" in flex["nota"]
    assert any(d["label"].startswith("Reintegro de Mercado Libre por envíos Flex (10%)") for d in bonos["detalle"])


def test_sin_flex_no_aparece_ninguna_linea_de_flex():
    a = f.agrupar_factura(FACTURA, flex_neto=0.0, flex_reintegro=0.10)
    assert not any("Flex" in d["label"] for fila in a["filas"] for d in fila["detalle"])


def test_una_factura_vacia_o_ausente_no_rompe():
    assert f.agrupar_factura(None)["filas"] == [] and f.agrupar_factura({})["total"] == 0
    assert f.agrupar_factura(_factura([]))["total_factura"] == 0


# ── Los cargos mensuales que no están en cada venta ─────────────────────────────────────────────────────────────────────────────────────────
def test_los_cargos_fuera_de_ventas_son_eshop_reputacion_y_servicios_de_full():
    fijos = f.fijos_de_resumen(FACTURA)
    assert set(fijos) == {"CESM", "CSTP", "CFWA"}                                    # CDSD se anuló completo (BDSD): no queda nada
    assert fijos["CESM"]["monto"] == 150 and fijos["CESM"]["label"] == "Mantenimiento de eShop"
    assert fijos["CFWA"]["label"] == "Almacenamiento en FULL"


def test_la_devolucion_se_descuenta_neta_de_su_anulacion():
    sin_anular = _factura([_cargo("CDSD", 90.0)])
    assert f.fijos_de_resumen(sin_anular)["CDSD"]["monto"] == 90
    anulada_a_medias = _factura([_cargo("CDSD", 90.0)], [{"type": "BDSD", "amount": -30.0}])
    assert f.fijos_de_resumen(anulada_a_medias)["CDSD"]["monto"] == 60
    assert "CDSD" not in f.fijos_de_resumen(_factura([_cargo("CDSD", 90.0)], [{"type": "BDSD", "amount": -90.0}]))
    assert "CDSD" not in f.fijos_de_resumen(_factura([_cargo("CDSD", 10.0)], [{"type": "BDSD", "amount": -90.0}]))      # la anulación no genera crédito


def test_la_comision_el_envio_y_la_publicidad_no_se_cuentan_dos_veces():
    """Eso ya está en cada venta (comisión, envío) y en la publicidad por publicación: acá solo van los cargos que no están en ninguna venta."""
    fijos = f.fijos_de_resumen(_factura([_cargo("CVFV", 999.0), _cargo("CFF", 999.0), _cargo("PADS", 999.0), _cargo("IIBB", 999.0)]))
    assert fijos == {}


def test_los_retiros_y_descartes_de_full_tambien_cuentan():
    fijos = f.fijos_de_resumen(_factura([_cargo("CFRS", 25480.0, "Cargos de envíos full", "Cargo por retiro o descarte de stock Full")]))
    assert fijos["CFRS"]["monto"] == 25480.0


# ── Repartir por día ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_un_periodo_cerrado_se_reparte_entre_todos_sus_dias():
    # 09/08 al 08/09 = 31 días: un rango de 31 días exactos se lleva todo; uno de 2 días, 2/31
    assert f.factor_de_reparto("2026-08-09", "2026-09-08", False, "2026-08-09", "2026-09-08", date(2026, 10, 7)) == 1.0
    assert abs(f.factor_de_reparto("2026-08-09", "2026-09-08", False, "2026-09-07", "2026-10-07", date(2026, 10, 7)) - 2 / 31) < 1e-9


def test_un_rango_fuera_del_periodo_no_se_lleva_nada():
    assert f.factor_de_reparto("2026-08-09", "2026-09-08", False, "2026-09-09", "2026-10-07", date(2026, 10, 7)) == 0.0
    assert f.factor_de_reparto("2026-08-09", "2026-09-08", False, "2026-07-01", "2026-08-08", date(2026, 10, 7)) == 0.0


def test_un_periodo_abierto_se_reparte_entre_los_dias_que_ya_pasaron():
    # período 09/09 al 08/10 con hoy = 07/10: 29 días transcurridos; los últimos 29 días se llevan el 100 % de lo acumulado
    assert f.factor_de_reparto("2026-09-09", "2026-10-08", True, "2026-09-09", "2026-10-07", date(2026, 10, 7)) == 1.0
    assert f.factor_de_reparto("2026-09-09", "2026-10-08", True, "2026-10-01", "2026-10-07", date(2026, 10, 7)) == 7 / 29


def test_repartir_suma_la_parte_de_cada_periodo_y_junta_por_nombre():
    periodos = [
        {"desde": "2026-08-09", "hasta": "2026-09-08", "abierto": False, "fijos": {"CESM": {"label": "Mantenimiento de eShop", "monto": 310.0}, "CSTP": {"label": "Cargo de reputación", "monto": 620.0}}},
        {"desde": "2026-09-09", "hasta": "2026-10-08", "abierto": True, "fijos": {"CESM": {"label": "Mantenimiento de eShop", "monto": 290.0}}},
    ]
    r = f.repartir_fijos(periodos, "2026-09-07", "2026-10-07", date(2026, 10, 7))
    esperado_eshop = 310 * 2 / 31 + 290 * 1.0
    esperado_reputacion = 620 * 2 / 31
    assert {i["label"]: i["monto"] for i in r["items"]} == {"Mantenimiento de eShop": round(esperado_eshop, 2), "Cargo de reputación": round(esperado_reputacion, 2)}
    assert r["total"] == round(round(esperado_eshop, 2) + round(esperado_reputacion, 2), 2)
    assert r["items"][0]["monto"] >= r["items"][1]["monto"]


def test_sin_periodos_no_se_descuenta_nada():
    assert f.repartir_fijos([], "2026-09-07", "2026-10-07", date(2026, 10, 7)) == {"total": 0.0, "items": []}

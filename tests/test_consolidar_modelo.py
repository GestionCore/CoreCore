"""Ganancia Real consolida por MODELO: los talles (publicaciones distintas en MeLi) se suman y los promedios son ponderados (total ÷ unidades)."""
import metricas as m


def _pub(titulo, unidades, facturado, costo_fab=0.0, cargos=0.0, envios=0.0, ads=0.0, thumb=None):
    return {"titulo": titulo, "thumbnail": thumb, "unidades": unidades, "facturado": facturado, "costo_fab": costo_fab, "cargos_meli": cargos, "envios": envios, "ads": ads}


def test_los_talles_de_un_modelo_son_una_sola_fila():
    por_pub = {
        "MLA1": _pub("Campera De Jean Hombre Negra Talle L", 40, 2000000, 680000, 300000, 200000, 100000, "L.jpg"),
        "MLA2": _pub("Campera De Jean Hombre Negra Talle XL", 10, 600000, 170000, 90000, 50000, 20000, "XL.jpg"),
        "MLA9": _pub("Medias Corta Hombre Pack", 5, 30000, 10000, 4000, 2000, 0),
    }
    filas = m.consolidar_por_modelo(por_pub)
    assert [f["titulo"] for f in filas] == ["Campera De Jean Hombre Negra", "Medias Corta Hombre Pack"]
    campera = filas[0]
    assert campera["unidades"] == 50 and len(campera["variantes"]) == 2
    assert campera["thumbnail"] == "L.jpg"                           # la foto es la de la publicación que más facturó
    assert [v["talle"] for v in campera["variantes"]] == ["L", "XL"]


def test_el_promedio_es_ponderado_no_un_promedio_simple_de_talles():
    # L: 40 u. a $50.000 con costo $30.000 (neto/u 20.000). XL: 10 u. a $60.000 con costo $55.000 (neto/u 5.000).
    # Promedio simple de talles: precio 55.000 y neto/u 12.500. Ponderado (el correcto): precio 2.600.000/50 = 52.000 y neto/u 850.000/50 = 17.000.
    por_pub = {
        "A": _pub("Remera Lisa Talle L", 40, 40 * 50000, 40 * 30000),
        "B": _pub("Remera Lisa Talle XL", 10, 10 * 60000, 10 * 55000),
    }
    f = m.consolidar_por_modelo(por_pub)[0]
    assert f["raw"]["precio_promedio"] == 52000.0
    assert f["raw"]["costo_u"] == 35000.0
    assert f["raw"]["neto_u"] == 17000.0
    assert f["raw"]["neto_total"] == 850000.0 == sum(v["raw"]["neto_total"] for v in f["variantes"])


def test_la_suma_de_los_modelos_es_el_total_de_las_publicaciones():
    por_pub = {f"M{i}": _pub(f"Producto {chr(65 + i % 3)} Talle {t}", 3 + i, 1000.0 * (i + 1), 100.0, 50.0, 20.0, 10.0) for i, t in enumerate(["S", "M", "L", "XL", "S", "M"])}
    filas = m.consolidar_por_modelo(por_pub)
    assert sum(f["unidades"] for f in filas) == sum(p["unidades"] for p in por_pub.values())
    assert round(sum(f["raw"]["neto_total"] for f in filas), 2) == round(sum(v["raw"]["neto_total"] for f in filas for v in f["variantes"]), 2)


def test_publicacion_sin_titulo_y_sin_talle():
    f = m.consolidar_por_modelo({"X": _pub(None, 2, 1000.0)})[0]
    assert f["titulo"] == "Sin nombre" and f["variantes"][0]["talle"] is None


def test_las_variantes_distinguen_clasica_de_premium():
    por_pub = {"A": {**_pub("Remera Lisa Talle L", 5, 5000.0), "tipo": "gold_special"}, "B": {**_pub("Remera Lisa Talle L", 3, 3600.0), "tipo": "gold_pro"}}
    tipos = {v["id_meli"]: v["tipo"] for v in m.consolidar_por_modelo(por_pub)[0]["variantes"]}
    assert tipos == {"A": "Clásica", "B": "Premium"}

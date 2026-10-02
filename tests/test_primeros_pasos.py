from dashboard import armar_primeros_pasos


def _claves(r):
    return [p["clave"] for p in r["pasos"]]


def test_cuenta_nueva_sin_costos_muestra_lo_que_falta():
    r = armar_primeros_pasos(83, 0)
    assert _claves(r) == ["cuenta", "catalogo", "costos"]
    assert (r["hechos"], r["total"]) == (2, 3)
    costos = r["pasos"][2]
    assert not costos["hecho"] and costos["href"] == "/costos" and "0 de 83" in costos["detalle"]


def test_con_la_mayoria_de_costos_cargados_el_paso_se_da_por_hecho_y_la_tarjeta_desaparece():
    assert armar_primeros_pasos(83, 75) is None          # 90 %
    assert armar_primeros_pasos(83, 74) is not None      # 89 %


def test_sin_publicaciones_activas_no_se_da_nada_por_hecho_salvo_la_conexion():
    r = armar_primeros_pasos(0, 0)
    assert [p["hecho"] for p in r["pasos"]] == [True, False, False]


def test_flex_solo_aparece_si_la_cuenta_lo_tiene_confirmado():
    assert "flex" not in _claves(armar_primeros_pasos(10, 10, {"flex": False}) or {"pasos": []})
    sin_precio = [{"id": 1, "precio": None, "resto": True}]
    r = armar_primeros_pasos(10, 10, {"flex": True}, sin_precio)
    assert _claves(r)[-1] == "flex" and not r["pasos"][-1]["hecho"]
    assert armar_primeros_pasos(10, 10, {"flex": True}, [{"id": 1, "precio": 2500, "resto": True}]) is None


def test_capacidad_ausente_no_agrega_pasos():
    assert armar_primeros_pasos(10, 10, {}, None) is None
    assert armar_primeros_pasos(10, 10, None, None) is None


def test_los_enlaces_del_checklist_apuntan_a_algo_que_existe():
    import re
    costos = open("templates/costos.html", encoding="utf-8").read()
    r = armar_primeros_pasos(10, 0, {"flex": True}, [{"id": 1, "precio": None, "resto": True}])
    for p in r["pasos"]:
        if p.get("href", "").startswith("/costos#"):
            assert re.search(r'id="%s"' % p["href"].split("#")[1], costos)

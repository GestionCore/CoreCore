import re

from onboarding import armar_checklist


def _ids(r):
    return [p["id"] for p in r["pasos"]]


def _estado(r):
    return {p["id"]: p["completo"] for p in r["pasos"]}


def test_cuenta_nueva_sin_costos_ni_gastos():
    r = armar_checklist(True, True, activas=83, con_costo=0, tiene_gastos=False, tiene_ventas=True)
    assert _ids(r) == ["onboarding", "sync", "costos", "gastos", "ventas"]
    assert _estado(r) == {"onboarding": True, "sync": True, "costos": False, "gastos": False, "ventas": True}
    assert (r["completos"], r["total"], r["porcentaje"]) == (3, 5, 60)
    assert "0 de 83" in r["pasos"][2]["detalle"] and r["pasos"][2]["link"] == "/costos"


def test_el_paso_de_costos_se_da_por_hecho_con_la_mayoria_cargada():
    assert _estado(armar_checklist(True, True, 83, 75, True, True))["costos"]          # 90 %
    assert not _estado(armar_checklist(True, True, 83, 74, True, True))["costos"]      # 89 %
    assert not _estado(armar_checklist(True, True, 0, 0, True, True))["costos"]        # sin publicaciones activas no hay nada que dar por hecho


def test_con_un_solo_costo_cargado_ya_no_alcanza():
    """Antes bastaba con uno: la ganancia seguía inflada para el resto."""
    assert not _estado(armar_checklist(True, True, 21, 1, True, True))["costos"]


def test_todo_hecho_da_100():
    r = armar_checklist(True, True, 10, 10, True, True)
    assert r["porcentaje"] == 100 and r["completos"] == r["total"]


def test_flex_solo_aparece_si_la_cuenta_lo_tiene_confirmado():
    assert "flex" not in _ids(armar_checklist(True, True, 10, 10, True, True, {"flex": False}))
    assert "flex" not in _ids(armar_checklist(True, True, 10, 10, True, True, {}))
    assert "flex" not in _ids(armar_checklist(True, True, 10, 10, True, True, None))
    r = armar_checklist(True, True, 10, 10, True, True, {"flex": True}, [{"id": 1, "precio": None, "resto": True}])
    assert "flex" in _ids(r) and not _estado(r)["flex"]
    assert _estado(armar_checklist(True, True, 10, 10, True, True, {"flex": True}, [{"id": 1, "precio": 2500, "resto": True}]))["flex"]


def test_los_enlaces_del_checklist_apuntan_a_algo_que_existe():
    costos = open("templates/costos.html", encoding="utf-8").read()
    r = armar_checklist(True, True, 10, 0, False, True, {"flex": True}, [{"id": 1, "precio": None, "resto": True}])
    anclas = [p["link"].split("#")[1] for p in r["pasos"] if p.get("link") and "#" in p["link"]]
    assert anclas
    for a in anclas:
        assert re.search(r'id="%s"' % a, costos)


def test_el_checklist_se_mide_sobre_la_cuenta_activa():
    """Un usuario con dos cuentas no puede ver el progreso de la otra: la conexión se abre con cuenta_id."""
    import inspect
    import onboarding
    assert "db.conexion_usuario(usuario_id, cuenta_id)" in inspect.getsource(onboarding.obtener_checklist_progreso)

"""La navegación se declara en nav_config.py: estas pruebas evitan que el menú, las pestañas y las rutas se desincronicen (una pantalla en el menú que no existe, o que existe sin estar en ninguna sección)."""
import glob
import os
import re

import nav_config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTES = {os.path.basename(p): open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(RAIZ, "*.py"))}
CODIGO = "\n".join(FUENTES.values())
TODAS = [(clave, p) for clave, s in nav_config.GRUPOS_NAV.items() for p in s["paginas"]]
# pantallas que llevan active_nav pero no son una sección del menú (cuenta, administración, páginas a las que se llega por un link)
SIN_SECCION = {"admin", "suscripcion", "referidos", "cuenta"}


def test_cada_pantalla_aparece_una_sola_vez_en_el_menu():
    claves = [p["nav_key"] for _, p in TODAS]
    destinos = [(p["endpoint"], p.get("ancla")) for _, p in TODAS]                 # varias pestañas pueden vivir en una misma pantalla (mismo endpoint, distinta ancla)
    assert len(claves) == len(set(claves)) and len(destinos) == len(set(destinos))


def test_cada_pantalla_del_menu_tiene_su_ruta_y_su_vista():
    for _, p in TODAS:
        assert re.search(r'@app\.route\("' + re.escape(p["href"]) + r'"', CODIGO), f"no hay ruta para {p['href']}"
        assert re.search(r"def " + re.escape(p["endpoint"]) + r"\(", CODIGO), f"no existe la vista {p['endpoint']}"


def test_cada_active_nav_pertenece_a_una_seccion():
    """Una plantilla con un active_nav que no está en ninguna sección queda sin el menú resaltado ni pestañas."""
    usados = set(re.findall(r'active_nav="([a-z_]+)"', CODIGO))
    sueltos = usados - set(nav_config.SECCION_DE_NAV) - SIN_SECCION
    assert not sueltos, sueltos


def test_cada_seccion_tiene_icono_en_el_menu():
    base = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    iconos = set(re.findall(r'<symbol id="icon-([\w-]+)"', base))
    for clave, s in nav_config.GRUPOS_NAV.items():
        assert s["icono"] in iconos, f"la sección {clave} usa el ícono {s['icono']}, que no está en el sprite de base.html"


def test_cada_titulo_de_pantalla_del_menu_lleva_su_icono():
    for _, p in TODAS:
        plantilla = p["nav_key"] + ".html"
        ruta = os.path.join(RAIZ, "templates", plantilla)
        if os.path.exists(ruta):
            assert "page-title-icono" in open(ruta, encoding="utf-8").read(), f"{plantilla} no tiene el ícono en su título"


def test_el_mas_usado_solo_se_calcula_donde_hay_algo_que_elegir():
    assert nav_config.calcular_mas_usado({"dashboard": 99}) == {}                      # una sola pantalla: nada que destacar
    assert nav_config.calcular_mas_usado({"stock": 5, "stock_masivo": 1}) == {"stock": "stock"}
    assert nav_config.calcular_mas_usado({"stock": 2}) == {}                           # por debajo del umbral

"""
Tablas que se ordenan por columna (static/js/tablas.js): Promociones (con descuento, impacto, campañas de MeLi), gastos de Costos e historial de cada producto de Competencia.
Las fechas se ordenan por su valor ISO (data-orden), no por el texto «5 oct»; los vacíos van al final; ninguna columna con botón/acción es ordenable.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _html(nombre):
    return open(os.path.join(RAIZ, "templates", nombre), encoding="utf-8").read()


def _tablas(html):
    return re.findall(r"<table[^>]*>.*?</thead>", html, flags=re.S)


def test_las_tablas_de_promociones_costos_y_competencia_son_ordenables():
    esperadas = {"promociones.html": 3, "costos.html": 1, "competencia.html": 1}
    for nombre, cantidad in esperadas.items():
        html = _html(nombre)
        ordenables = [t for t in _tablas(html) if "data-ordenable" in t.split(">", 1)[0]]
        assert len(ordenables) == cantidad, (nombre, len(ordenables))
        for t in ordenables:
            assert 'data-orden="' in t


def test_las_fechas_se_ordenan_por_su_valor_exacto_y_la_mas_nueva_primero():
    promos = _html("promociones.html")
    assert '<th data-orden="texto" data-primero="desc">Período</th>' in promos and 'data-orden="{{ imp.fecha_inicio }}"' in promos
    assert 'data-orden="{{ g.fecha }}"' in _html("costos.html") and 'data-orden="{{ h.fecha }}"' in _html("competencia.html")


def test_el_resultado_y_el_descuento_se_ordenan_por_numero_y_lo_que_no_tiene_base_va_al_final():
    promos = _html("promociones.html")
    assert "data-orden=\"{{ imp.variacion_pct if imp.variacion_pct is not none else '' }}\"" in promos        # «Sin base previa» = vacío = siempre al final
    assert 'data-orden="{{ p.descuento_pct }}"' in promos                                                      # el descuento se muestra con «-»: se ordena por el valor positivo


def test_la_ofertas_relampago_muertas_ya_no_estan():
    """Mostraban un formulario hacia una ruta que no existe (y el contexto mandaba la lista siempre vacía)."""
    assert "relampago" not in _html("promociones.html") and "participar_relampago" not in open(os.path.join(RAIZ, "app.py"), encoding="utf-8").read()

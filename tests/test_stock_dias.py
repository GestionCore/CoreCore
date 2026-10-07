"""
Cuántos días alcanza el stock de un modelo y cómo se muestra en Stock ("Alcanza para"). Funciones puras: sin base.
"""
import analisis_stock as a


def test_los_dias_son_stock_sobre_ritmo_diario():
    # 28 unidades vendidas en la ventana de 14 días = 2 por día; con 10 en stock alcanzan 5 días
    assert a.dias_de_stock(10, 28) == 5.0
    assert a.dias_de_stock(3, 7) == 6.0                    # 0,5 por día
    assert a.dias_de_stock(0, 14) == 0.0                   # sin stock y con ventas: se agotó


def test_sin_ventas_no_hay_ritmo_y_no_se_inventa_un_numero():
    assert a.dias_de_stock(50, 0) is None
    assert a.dias_de_stock(50, None) is None


def test_la_ventana_es_la_misma_que_usa_que_reponer():
    """Si la columna y la lista de reposición usaran ventanas distintas, un modelo diría 10 días en una y 4 en la otra."""
    assert a.dias_de_stock(14, 14) == 14.0
    assert a.dias_de_stock(14, 14, ventana_dias=a.VENTANA_DIAS) == 14.0


def test_agotado_manda_sobre_todo_lo_demas():
    assert a.presentar_dias_de_stock(0.0, 0) == ("Agotado", "danger")
    assert a.presentar_dias_de_stock(None, 0) == ("Agotado", "danger")


def test_sin_ventas_va_un_guion_y_no_preocupa():
    """No se repite «Sin ventas»: la columna de ventas ya lo dice. Acá solo hace falta no inventar un plazo."""
    assert a.presentar_dias_de_stock(None, 40) == ("—", "neutral")


def test_rojo_hasta_el_umbral_de_reposicion_naranja_hasta_dos_semanas_y_neutro_despues():
    assert a.presentar_dias_de_stock(a.UMBRAL_DIAS_RESTANTES, 10) == ("~5 días", "danger")
    assert a.presentar_dias_de_stock(a.UMBRAL_DIAS_RESTANTES + 0.4, 10)[1] == "danger"    # redondea a 5
    assert a.presentar_dias_de_stock(9.2, 10) == ("~9 días", "warn")
    assert a.presentar_dias_de_stock(a.VENTANA_DIAS, 10) == ("~14 días", "warn")
    assert a.presentar_dias_de_stock(30, 10) == ("~30 días", "neutral")


def test_singular_y_menos_de_un_dia():
    assert a.presentar_dias_de_stock(1.0, 2) == ("~1 día", "danger")
    assert a.presentar_dias_de_stock(0.4, 2) == ("menos de 1 día", "danger")


def test_los_plazos_largos_no_muestran_numeros_que_nadie_va_a_creer():
    assert a.presentar_dias_de_stock(120, 100) == ("+90 días", "neutral")
    assert a.presentar_dias_de_stock(900, 100) == ("+1 año", "neutral")

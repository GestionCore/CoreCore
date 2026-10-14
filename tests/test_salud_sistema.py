import pytest

from salud_sistema import _duracion, estado_de_cuenta


@pytest.mark.parametrize("args, tono", [
    ((False, True, True, 1), "danger"),        # desconectada
    ((True, False, True, 1), "danger"),        # sin tokens
    ((True, True, False, None), "warn"),       # primera sincronización
    ((True, True, True, None), "warn"),        # nunca sincronizó ventas
    ((True, True, True, 2), "ok"),
    ((True, True, True, 12), "ok"),
    ((True, True, True, 13), "warn"),          # se salteó algún ciclo
    ((True, True, True, 31), "danger"),
])
def test_estado_de_cuenta(args, tono):
    assert estado_de_cuenta(*args)[0] == tono


def test_una_cuenta_desconectada_gana_sobre_cualquier_otro_estado():
    assert estado_de_cuenta(False, False, False, None)[0] == "danger"
    assert "volver a conectar" in estado_de_cuenta(False, True, True, 1)[1]


@pytest.mark.parametrize("minutos, texto", [(5, "5 min"), (59, "59 min"), (60, "1 h"), (180, "3 h"), (60 * 48, "2 días")])
def test_duracion_legible(minutos, texto):
    assert _duracion(minutos) == texto


def test_migraciones_pendientes_compara_por_el_prefijo_numerico():
    from salud_sistema import migraciones_pendientes
    disco = ["0001_alertas.sql", "0002_soft_delete.sql", "0003_otra.sql"]
    assert migraciones_pendientes(disco, {"0001", "0002", "0003"}) == []
    assert migraciones_pendientes(disco, {"0001"}) == ["0002_soft_delete.sql", "0003_otra.sql"]


def test_el_runner_y_el_panel_leen_las_versiones_igual():
    """migrate.py guarda el prefijo numérico: si cambia el formato, el panel mostraría todo como pendiente."""
    import re
    fuente = open("migrate.py", encoding="utf-8").read()
    assert re.search(r"match\.group\(1\)", fuente)


# ── Relevamiento diario de mercado: la señal para enterarse de que Mercado Libre cerró un endpoint ────────────────────────────────────────

def _corrida(fecha=None, fin=True, categorias=39, llamadas=396, errores=0, con_tendencias=37, tipo="diario"):
    from datetime import date, datetime, timedelta
    from utils import ARGENTINA
    fecha = fecha or date(2030, 5, 10)
    inicio = datetime(2030, 5, 10, 4, 0, tzinfo=ARGENTINA)
    return {"tipo": tipo, "fecha": fecha, "inicio": inicio, "fin": (inicio + timedelta(minutes=4)) if fin else None, "categorias": categorias, "llamadas": llamadas,
            "errores": errores, "detalle": {"con_tendencias": con_tendencias}}


def _ahora(hora, minuto=0, dia=10):
    from datetime import datetime
    from utils import ARGENTINA
    return datetime(2030, 5, dia, hora, minuto, tzinfo=ARGENTINA)


def test_el_relevamiento_al_dia_esta_bien():
    from salud_sistema import estado_del_relevamiento
    tono, texto = estado_del_relevamiento([_corrida()], _ahora(9))
    assert tono == "ok" and "39 categorías" in texto


def test_sin_ninguna_corrida_avisa_y_no_falla():
    from salud_sistema import estado_del_relevamiento
    assert estado_del_relevamiento([], _ahora(9))[0] == "warn"
    assert estado_del_relevamiento([_corrida(tipo="muestra")], _ahora(9))[0] == "warn"        # solo cuentan las corridas diarias


def test_si_a_las_seis_todavia_no_corrio_hoy_es_un_problema_pero_antes_no():
    from datetime import date
    from salud_sistema import estado_del_relevamiento
    ayer = _corrida(fecha=date(2030, 5, 9))
    assert estado_del_relevamiento([ayer], _ahora(3, 30))[0] == "ok"                           # todavía no es la hora
    tono, texto = estado_del_relevamiento([ayer], _ahora(6, 0))
    assert tono == "danger" and "09/05" in texto


def test_un_endpoint_cerrado_se_nota_porque_no_trae_nada_en_ninguna_categoria():
    from salud_sistema import estado_del_relevamiento
    assert estado_del_relevamiento([_corrida(categorias=0, llamadas=40, errores=40, con_tendencias=0)], _ahora(9))[0] == "danger"
    tono, texto = estado_del_relevamiento([_corrida(con_tendencias=0)], _ahora(9))
    assert tono == "danger" and "/trends" in texto                                             # midió las categorías pero ninguna lista de búsquedas


def test_los_errores_solo_avisan_si_son_mas_de_uno_cada_veinte_llamadas():
    from salud_sistema import estado_del_relevamiento
    assert estado_del_relevamiento([_corrida(llamadas=400, errores=20)], _ahora(9))[0] == "ok"       # 5 %: ruido normal
    assert estado_del_relevamiento([_corrida(llamadas=400, errores=21)], _ahora(9))[0] == "warn"


def test_un_relevamiento_que_empezo_y_no_termino_se_da_por_cortado_pasada_media_hora():
    from salud_sistema import estado_del_relevamiento
    assert estado_del_relevamiento([_corrida(fin=False)], _ahora(4, 10))[0] == "ok"           # corriendo
    assert estado_del_relevamiento([_corrida(fin=False)], _ahora(4, 31))[0] == "danger"

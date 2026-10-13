"""
Cobertura de variantes clave (reemplaza a la curva de talles M/L/XL, que solo existía para ropa): avisa cuando se queda sin stock la variante que aporta más del 30 % de las ventas de su modelo.
Sirve para un buzo talle M, un disco de 1 TB o un celular de 128 GB. Los números están hechos a mano.
"""
import os

import pytest

import analisis_stock as a

CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _v(modelo, id_variante, unidades, stock, titulo="Disco SSD Interno 1 TB", talle=None, etiqueta=None, id_meli=None):
    return {"modelo": modelo, "id_variante": id_variante, "id_meli": id_meli or f"MLA-{id_variante}", "titulo": titulo, "talle": talle, "etiqueta": etiqueta, "stock": stock, "unidades": unidades}


def test_avisa_de_la_variante_que_aporta_mas_del_30_por_ciento_y_no_tiene_stock():
    filas = [_v("F1", "a", 10, 0, etiqueta="1 TB"), _v("F1", "b", 5, 8, etiqueta="512 GB"), _v("F1", "c", 1, 2, etiqueta="256 GB")]       # a aporta 10 de 16 = 62 %
    (aviso,) = a.variantes_clave_agotadas(filas)
    assert aviso["variante"] == "1 TB" and aviso["aporta_pct"] == 62 and aviso["unidades"] == 10 and aviso["id_variante"] == "a" and aviso["id_referencia"] == "MLA-a"


def test_una_variante_clave_con_stock_no_avisa_ni_una_agotada_que_casi_no_vende():
    filas = [_v("F1", "a", 10, 5), _v("F1", "b", 5, 8), _v("F1", "c", 1, 0)]                  # c está agotada pero aporta 6 %: no es clave
    assert a.variantes_clave_agotadas(filas) == []


def test_el_borde_es_estricto_exactamente_30_por_ciento_no_alcanza():
    assert a.variantes_clave_agotadas([_v("F1", "a", 3, 0), _v("F1", "b", 7, 4)]) == []                          # 3 de 10 = 30 %
    assert len(a.variantes_clave_agotadas([_v("F1", "a", 4, 0), _v("F1", "b", 6, 4)])) == 1                      # 4 de 10 = 40 %


def test_un_modelo_con_una_sola_variante_no_cuenta_eso_es_un_producto_agotado():
    assert a.variantes_clave_agotadas([_v("F1", "a", 50, 0)]) == []


def test_con_muy_pocas_ventas_el_reparto_no_dice_nada():
    assert a.variantes_clave_agotadas([_v("F1", "a", 3, 0), _v("F1", "b", 1, 5)]) == []          # 4 unidades en total: menos que el mínimo
    assert len(a.variantes_clave_agotadas([_v("F1", "a", 4, 0), _v("F1", "b", 1, 5)])) == 1      # 5: alcanza


def test_cada_modelo_se_mide_por_separado_y_salen_primero_las_que_mas_venden():
    filas = [_v("F1", "a", 6, 0), _v("F1", "b", 4, 3), _v("F2", "c", 20, 0), _v("F2", "d", 5, 3), _v("F3", "e", 9, 4), _v("F3", "f", 9, 4)]
    assert [x["id_variante"] for x in a.variantes_clave_agotadas(filas)] == ["c", "a"]


def test_el_nombre_del_modelo_es_el_titulo_sin_el_talle_conocido():
    filas = [_v("F1", "a", 8, 0, titulo="Buzo Manta Gris XL", talle="XL"), _v("F1", "b", 4, 4, titulo="Buzo Manta Gris M", talle="M")]
    assert a.variantes_clave_agotadas(filas)[0]["modelo"] == "Buzo Manta Gris" and a.variantes_clave_agotadas(filas)[0]["variante"] == "XL"      # sin etiqueta se usa el talle
    sin_nada = [_v("F1", "a", 8, 0, titulo="Pantalla 4K"), _v("F1", "b", 4, 4, titulo="Pantalla 2K")]
    assert a.variantes_clave_agotadas(sin_nada)[0]["variante"] == "Única"


@CON_BASE
def test_la_consulta_corre_contra_la_base_real_y_devuelve_el_formato_esperado():
    import db
    with db.conexion_admin() as conexion:
        resultado = a.evaluar_cobertura_variantes(conexion.cursor())
    assert isinstance(resultado, list)
    for aviso in resultado:
        assert set(aviso) == {"modelo", "id_referencia", "id_variante", "variante", "aporta_pct", "unidades"} and aviso["aporta_pct"] > 30


def test_la_curva_de_talles_ya_no_existe():
    assert not hasattr(a, "evaluar_curva_talles") and not hasattr(a, "CENTRALES")
    import utils
    assert not hasattr(utils, "extraer_talle")                   # el talle sale del atributo de Mercado Libre, nunca de una regex sobre el título

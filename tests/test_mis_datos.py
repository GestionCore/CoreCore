"""
"Descargar mis datos": cada carpeta del zip tiene SOLO las filas de su cuenta, nunca los tokens de Mercado Libre, y ningún dato de otro usuario. La parte de
privacidad se prueba contra la base REAL (se omite sin DATABASE_URL); lo demás, sin base.
"""
import csv
import io
import os
import zipfile

import pytest

import mis_datos


def test_nombres_de_carpeta_seguros_y_unicos():
    usadas = set()
    assert mis_datos.nombre_de_carpeta({"id": 1, "nickname": "MI TIENDA", "nombre_negocio": None}, usadas) == "MI_TIENDA"
    assert mis_datos.nombre_de_carpeta({"id": 2, "nickname": "MI TIENDA"}, usadas) == "MI_TIENDA_2"          # repetido: se distingue por id
    assert mis_datos.nombre_de_carpeta({"id": 3, "nickname": "../../etc/passwd"}, usadas) == "etc_passwd"        # nada de rutas
    assert mis_datos.nombre_de_carpeta({"id": 4, "nickname": "///"}, usadas) == "cuenta_4"
    assert mis_datos.nombre_de_carpeta({"id": 5, "nickname": ".."}, usadas) == "cuenta_5"                         # ".." sería una ruta al descomprimir
    assert ".." not in mis_datos.nombre_de_carpeta({"id": 6, "nickname": "a..b"}, usadas).split("/")


def test_no_se_exportan_los_tokens_ni_la_cache():
    assert {"meli_tokens", "cache_valores"} <= mis_datos.TABLAS_EXCLUIDAS


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")
def test_cada_carpeta_tiene_solo_las_filas_de_su_cuenta():
    import db
    from auth import registro
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id FROM cuentas_meli GROUP BY usuario_id ORDER BY count(*) DESC, usuario_id LIMIT 1")
        usuario_id = cur.fetchone()[0]
    cuentas = registro.obtener_cuentas_de_usuario(usuario_id)
    contenido, resumen = mis_datos.armar_zip(usuario_id, cuentas)
    zf = zipfile.ZipFile(io.BytesIO(contenido))
    nombres = zf.namelist()
    assert "LEEME.txt" in nombres and "usuario.csv" in nombres
    assert not any("meli_tokens" in n or "cache_valores" in n for n in nombres)

    usadas, carpeta_de = set(), {}
    for cuenta in cuentas:
        carpeta_de[mis_datos.nombre_de_carpeta(cuenta, usadas)] = cuenta["id"]
    revisadas = 0
    for nombre in nombres:
        if "/" not in nombre:
            continue
        carpeta, archivo = nombre.split("/", 1)
        assert carpeta in carpeta_de, nombre                              # ninguna carpeta que no sea de una cuenta del usuario
        filas = list(csv.DictReader(io.StringIO(zf.read(nombre).decode("utf-8"))))
        if filas and "cuenta_id" in filas[0]:
            assert {f["cuenta_id"] for f in filas} == {str(carpeta_de[carpeta])}, f"{nombre} trae filas de otra cuenta"
            revisadas += 1
    assert revisadas >= 1

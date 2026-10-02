"""El respaldo tiene los datos de TODOS los usuarios: tiene que quedar fuera del proyecto, cifrado si hay clave, y sin los tokens salvo que se pidan."""
import contextlib
import io
import os
import zipfile

import pytest
from cryptography.fernet import Fernet, InvalidToken

import respaldo


class CursorFalso:
    """Lo mínimo del cursor de psycopg que usa armar_zip: lista de tablas, COPY y conteo."""

    def __init__(self, tablas):
        self.tablas, self._ultima, self._tabla = tablas, None, None

    def execute(self, sql, *_):
        self._ultima = sql
        if sql.startswith("SELECT count(*)"):
            self._tabla = sql.split('"')[1]

    def fetchall(self):
        return [(t,) for t in self.tablas]

    def fetchone(self):
        return (len(self.tablas[self._tabla]) if isinstance(self.tablas, dict) else 3,)

    @contextlib.contextmanager
    def copy(self, sql):
        tabla = sql.split('"')[1]
        yield [f"id\n1,{tabla}\n".encode()]


def test_no_guarda_dentro_del_proyecto(tmp_path):
    with pytest.raises(ValueError):
        respaldo.validar_carpeta(os.path.join(respaldo.RAIZ, "respaldos"))
    with pytest.raises(ValueError):
        respaldo.validar_carpeta(respaldo.RAIZ)
    assert respaldo.validar_carpeta(str(tmp_path)) == os.path.realpath(tmp_path)


def test_la_carpeta_por_defecto_esta_fuera_del_proyecto(monkeypatch):
    monkeypatch.delenv("RESPALDOS_CARPETA", raising=False)
    respaldo.validar_carpeta(respaldo.carpeta_por_defecto())            # no lanza


def test_los_tokens_solo_entran_si_se_piden():
    cursor = CursorFalso(["ventas", "meli_tokens", "schema_migrations"])
    sin, _ = respaldo.armar_zip(cursor)
    nombres = set(zipfile.ZipFile(io.BytesIO(sin)).namelist())
    assert nombres == {"ventas.csv", "LEEME.txt"}
    con, _ = respaldo.armar_zip(CursorFalso(["ventas", "meli_tokens"]), con_tokens=True)
    assert "meli_tokens.csv" in zipfile.ZipFile(io.BytesIO(con)).namelist()


def test_cifrar_y_descifrar_ida_y_vuelta_y_clave_equivocada():
    contenido, _ = respaldo.armar_zip(CursorFalso(["ventas"]))
    clave = Fernet.generate_key()
    cifrado = respaldo.cifrar(contenido, clave)
    assert cifrado != contenido and b"ventas" not in cifrado
    assert respaldo.descifrar(cifrado, clave) == contenido
    with pytest.raises(InvalidToken):
        respaldo.descifrar(cifrado, Fernet.generate_key())

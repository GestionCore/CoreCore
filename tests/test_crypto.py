import pytest
from cryptography.fernet import Fernet

import config
import crypto_utils


@pytest.fixture
def claves(monkeypatch):
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", vieja)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY_ANTERIOR", "", raising=False)
    return vieja, nueva


def test_cifra_y_descifra(claves):
    assert crypto_utils.descifrar(crypto_utils.cifrar("APP_USR-123")) == "APP_USR-123"
    assert crypto_utils.cifrar("") is None and crypto_utils.descifrar(None) is None


def test_al_rotar_lo_viejo_se_sigue_leyendo_con_la_clave_anterior(claves, monkeypatch):
    vieja, nueva = claves
    guardado = crypto_utils.cifrar("secreto")
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", nueva)
    with pytest.raises(RuntimeError):                       # sin dejar la anterior, no se puede leer
        crypto_utils.descifrar(guardado)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY_ANTERIOR", vieja)
    assert crypto_utils.descifrar(guardado) == "secreto"
    assert not crypto_utils.usa_la_clave_vigente(guardado)


def test_recifrar_pasa_a_la_clave_nueva_y_ya_no_hace_falta_la_anterior(claves, monkeypatch):
    vieja, nueva = claves
    guardado = crypto_utils.cifrar("secreto")
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", nueva)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY_ANTERIOR", vieja)
    recifrado = crypto_utils.recifrar(guardado)
    assert crypto_utils.usa_la_clave_vigente(recifrado)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY_ANTERIOR", "")
    assert crypto_utils.descifrar(recifrado) == "secreto"

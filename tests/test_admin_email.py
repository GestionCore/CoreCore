"""ADMIN_EMAIL: tolera comillas, espacios y mayúsculas (se cargó a mano en Fly y un detalle así deja a la persona sin entrar a /admin sin ningún aviso), y admite varios."""
import config


def test_un_email_con_comillas_espacios_y_mayusculas():
    assert config.emails_admin("diegoarielsantiago@gmail.com") == {"diegoarielsantiago@gmail.com"}
    assert config.emails_admin("  'DiegoArielSantiago@Gmail.com'  ") == {"diegoarielsantiago@gmail.com"}
    assert config.emails_admin('"diegoarielsantiago@gmail.com"') == {"diegoarielsantiago@gmail.com"}


def test_varios_administradores():
    assert config.emails_admin("uno@x.com, Otro@Y.com;tercero@z.com otro_mas@w.com") == {"uno@x.com", "otro@y.com", "tercero@z.com", "otro_mas@w.com"}


def test_vacio_no_habilita_a_nadie():
    assert config.emails_admin("") == set() == config.emails_admin(None) == config.emails_admin("  ,  ; ")


def test_es_admin_compara_sin_importar_mayusculas_ni_espacios(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"yo@x.com"})
    assert config.es_admin("Yo@X.com ") and config.es_admin("yo@x.com")
    assert not config.es_admin("otro@x.com") and not config.es_admin(None) and not config.es_admin("")
    assert not config.es_admin("meli-1@pendiente.corelux.app")


def test_sin_administradores_nadie_es_admin(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    assert not config.es_admin("yo@x.com")

"""
Notificaciones de Mercado Libre sobre publicaciones: «items» (cambió algo) e «items_prices» (cambió el precio, p. ej. por una promoción) refrescan ESA publicación; los temas
que CoreLux no usa (public_offers, public_candidates…) se ignoran sin tocar nada ni fallar. Producción ya recibe los tres.
"""
import pytest

import sincronizador


@pytest.mark.parametrize("recurso, esperado", [
    ("/items/MLA123", "MLA123"), ("/items/MLA123/prices", "MLA123"), ("MLA123", "MLA123"), ("/items/MLA123/", "MLA123"), ("", ""), (None, ""), ("/items", "items"),
])
def test_el_id_de_la_publicacion_sale_del_recurso(recurso, esperado):
    assert sincronizador.id_item_del_recurso(recurso) == esperado


class _Cursor:
    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return (7, 3)                  # cuenta 7 del usuario 3


class _Conexion:
    def cursor(self):
        return _Cursor()


class _Prestada:
    def __enter__(self):
        return _Conexion()

    def __exit__(self, *a):
        return False


@pytest.fixture
def mundo(monkeypatch):
    refrescados = []
    monkeypatch.setattr(sincronizador.db, "conexion_admin", lambda: _Prestada())
    monkeypatch.setattr(sincronizador.db, "conexion_usuario", lambda u, c=None: _Prestada())
    monkeypatch.setattr(sincronizador.token_manager, "asegurar_token_valido", lambda cuenta: "token")
    monkeypatch.setattr(sincronizador, "sincronizar_item_individual", lambda cuenta, id_item, headers, cursor: refrescados.append((cuenta, id_item)))
    monkeypatch.setattr(sincronizador._antirrebote_webhook, "ejecutar", lambda clave, funcion: funcion())
    return refrescados


def test_un_cambio_de_precio_refresca_la_publicacion(mundo):
    sincronizador.procesar_notificacion_webhook("items_prices", "/items/MLA555/prices", 99)
    assert mundo == [(7, "MLA555")]


def test_un_cambio_de_la_publicacion_sigue_refrescandola(mundo):
    sincronizador.procesar_notificacion_webhook("items", "/items/MLA777", 99)
    assert mundo == [(7, "MLA777")]


@pytest.mark.parametrize("tema", ["public_offers", "public_candidates", "payments", "messages"])
def test_los_temas_que_no_se_usan_se_ignoran_sin_fallar(mundo, tema):
    sincronizador.procesar_notificacion_webhook(tema, "/algo/MLA1", 99)
    assert mundo == []

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


# ── Tabla explícita de temas (Ola 4, T31) ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tema, esperado", [
    ("items", "publicacion"), ("items_prices", "publicacion"), ("orders_v2", "ventas"), ("orders", "ventas"), ("shipments", "ventas"), ("questions", "preguntas"),
    ("claims", "reclamos"), ("post_purchase", "reclamos"), ("public_offers", "ignorado"), ("payments", "ignorado"), ("tema_inventado", "desconocido"),
])
def test_cada_tema_tiene_una_accion_dicha_en_una_tabla(tema, esperado):
    assert sincronizador.clasificar_tema(tema) == esperado


def test_un_tema_no_puede_estar_a_la_vez_atendido_e_ignorado():
    assert not (set(sincronizador.TEMAS_ATENDIDOS) & sincronizador.TEMAS_IGNORADOS)


def test_un_tema_ignorado_no_gasta_ni_una_consulta_ni_un_token(monkeypatch):
    llamadas = []
    monkeypatch.setattr(sincronizador.db, "conexion_admin", lambda: llamadas.append("base") or _Prestada())
    monkeypatch.setattr(sincronizador.token_manager, "asegurar_token_valido", lambda cuenta: llamadas.append("token") or "token")
    sincronizador.procesar_notificacion_webhook("public_offers", "/algo", 99)
    assert llamadas == []


def test_un_tema_nuevo_se_avisa_una_sola_vez_y_no_se_atiende(monkeypatch, capsys):
    monkeypatch.setattr(sincronizador, "_temas_no_vistos", set())
    monkeypatch.setattr(sincronizador.db, "conexion_admin", lambda: pytest.fail("no debería abrir la base"))
    for _ in range(3):
        sincronizador.procesar_notificacion_webhook("tema_nuevo_de_prueba", "/x", 99)
    salida = capsys.readouterr().out
    assert salida.count("tema nuevo que no está en la tabla") == 1 and "tema_nuevo_de_prueba" in salida

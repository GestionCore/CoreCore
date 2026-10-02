import contextlib

import salud_tokens
from auth import token_manager


class _Base:
    def __init__(self, ya_hay_alerta=False):
        self.ya_hay_alerta, self.sql = ya_hay_alerta, []

    @contextlib.contextmanager
    def conexion(self, *a, **k):
        base = self

        class Cur:
            def execute(self, sql, params=None):
                base.sql.append((" ".join(sql.split()), params))
                self.ultima = sql

            def fetchone(self):
                return (1,) if base.ya_hay_alerta and "SELECT id FROM alertas_usuario" in self.ultima else None

        yield type("C", (), {"cursor": lambda s: Cur()})()


def test_una_cuenta_desconectada_deja_una_alerta_con_link_para_reconectar(monkeypatch):
    base = _Base()
    monkeypatch.setattr(salud_tokens.db, "conexion_usuario", base.conexion)
    monkeypatch.setattr(salud_tokens, "_cuentas_activas", lambda: [(1, 10, "VENDEDOR1"), (2, 20, "VENDEDOR2")])

    def token(cuenta_id):
        if cuenta_id == 1:
            raise token_manager.CuentaDesconectada()
        return "ok"

    monkeypatch.setattr(salud_tokens.token_manager, "asegurar_token_valido", token)
    assert salud_tokens.verificar_tokens() == 1
    inserts = [p for s, p in base.sql if s.startswith("INSERT INTO alertas_usuario")]
    assert len(inserts) == 1 and inserts[0][2] == "token_vencido" and inserts[0][5] == "/reconectar" and "VENDEDOR1" in inserts[0][3]


def test_no_se_repite_la_alerta_mientras_siga_sin_leerse(monkeypatch):
    base = _Base(ya_hay_alerta=True)
    monkeypatch.setattr(salud_tokens.db, "conexion_usuario", base.conexion)
    assert salud_tokens.crear_alerta(10, 1, "token_vencido", "t", "m") is False
    assert not any(s.startswith("INSERT") for s, _ in base.sql)


def test_un_error_de_red_no_genera_alerta_a_la_persona(monkeypatch):
    base = _Base()
    monkeypatch.setattr(salud_tokens.db, "conexion_usuario", base.conexion)
    monkeypatch.setattr(salud_tokens, "_cuentas_activas", lambda: [(1, 10, "V")])
    monkeypatch.setattr(salud_tokens.token_manager, "asegurar_token_valido", lambda c: (_ for _ in ()).throw(ConnectionError("sin red")))
    assert salud_tokens.verificar_tokens() == 0 and base.sql == []

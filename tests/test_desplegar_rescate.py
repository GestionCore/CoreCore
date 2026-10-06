"""
Si un deploy deja producción caída, desplegar.py vuelve solo a la última versión que funcionaba (el 2026-10-06 la imagen nueva no arrancaba, las dos máquinas se apagaron y hubo que
volver a mano). Sin fly ni red: dobles de subprocess y de la consulta a /healthz.
"""
import json

import desplegar as d

RELEASES = [
    {"Version": 27, "Status": "failed", "ImageRef": "registry.fly.io/corecore:nueva-rota"},
    {"Version": 26, "Status": "complete", "ImageRef": "registry.fly.io/corecore:vieja-buena"},
    {"Version": 25, "Status": "failed", "ImageRef": "registry.fly.io/corecore:otra-rota"},
    {"Version": 24, "Status": "complete", "ImageRef": "registry.fly.io/corecore:mas-vieja"},
]


def test_la_ultima_release_buena_es_la_mas_reciente_que_termino_bien():
    assert d.ultima_release_buena(RELEASES) == "registry.fly.io/corecore:vieja-buena"
    assert d.ultima_release_buena([{"Status": "failed", "ImageRef": "x"}]) is None
    assert d.ultima_release_buena([]) is None and d.ultima_release_buena(None) is None
    assert d.ultima_release_buena([{"Status": "complete"}]) is None          # sin imagen no sirve


class _Fly:
    """Doble de subprocess.run: anota los comandos y contesta los --json."""

    def __init__(self, releases=RELEASES, maquinas=None):
        self.comandos, self.releases, self.maquinas = [], releases, maquinas or []

    def run(self, comando, **kw):
        self.comandos.append(comando[1:])
        salida = ""
        if "--json" in comando:
            salida = json.dumps(self.releases if "releases" in comando else self.maquinas)

        class R:
            returncode, stdout, stderr = 0, salida, ""
        return R()


def test_volver_atras_despliega_la_imagen_buena_y_levanta_las_maquinas_apagadas(monkeypatch):
    fly = _Fly(maquinas=[{"id": "m1", "state": "stopped"}, {"id": "m2", "state": "started"}, {"id": "m3", "state": "stopped"}])
    monkeypatch.setattr(d.subprocess, "run", fly.run)
    monkeypatch.setattr(d, "produccion_responde", lambda *a, **k: True)
    assert d.volver_atras("fly") is True
    despliegues = [c for c in fly.comandos if c[0] == "deploy"]
    assert despliegues == [["deploy", "-a", "corecore", "--image", "registry.fly.io/corecore:vieja-buena", "--strategy", "immediate"]]
    iniciadas = [c[2] for c in fly.comandos if c[:2] == ["machine", "start"]]
    assert iniciadas == ["m1", "m3"]                         # solo las apagadas


def test_volver_atras_sin_release_buena_no_despliega_nada(monkeypatch):
    fly = _Fly(releases=[{"Status": "failed", "ImageRef": "x"}])
    monkeypatch.setattr(d.subprocess, "run", fly.run)
    assert d.volver_atras("fly") is False
    assert not [c for c in fly.comandos if c[0] == "deploy"]


def test_si_producción_sigue_respondiendo_no_se_deshace_nada(monkeypatch, capsys):
    fly = _Fly()
    monkeypatch.setattr(d.subprocess, "run", fly.run)
    monkeypatch.setattr(d, "produccion_responde", lambda *a, **k: True)
    d.rescatar_si_esta_caida("fly")
    assert fly.comandos == [] and "No hay nada que deshacer" in capsys.readouterr().out


def test_si_producción_no_responde_se_vuelve_atras(monkeypatch, capsys):
    fly = _Fly()
    respuestas = iter([False, True])                           # primero caída, después (ya revertida) responde
    monkeypatch.setattr(d.subprocess, "run", fly.run)
    monkeypatch.setattr(d, "produccion_responde", lambda *a, **k: next(respuestas))
    d.rescatar_si_esta_caida("fly")
    salida = capsys.readouterr().out
    assert "NO responde" in salida and "volvió a responder" in salida
    assert any(c[0] == "deploy" and "vieja-buena" in " ".join(c) for c in fly.comandos)


def test_produccion_responde_reintenta_hasta_que_contesta(monkeypatch):
    codigos = iter([0, 502, 200])
    monkeypatch.setattr(d, "pedir", lambda ruta: (next(codigos), ""))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    assert d.produccion_responde(intentos=5, espera=1) is True
    monkeypatch.setattr(d, "pedir", lambda ruta: (0, "sin red"))
    assert d.produccion_responde(intentos=3, espera=1) is False

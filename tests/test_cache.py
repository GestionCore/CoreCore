import glob
import os
import re

import cache as c

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CacheRota:
    def get(self, *a, **k):
        raise ConnectionError("Redis no responde")

    def set(self, *a, **k):
        raise ConnectionError("Redis no responde")


def test_si_la_cache_falla_la_pagina_sigue(monkeypatch):
    """Antes un Redis caído (o ausente, como en Fly) hacía que cada página tirara 500."""
    monkeypatch.setattr(c, "cache", CacheRota())
    assert c.leer("x") is None
    c.guardar("x", 1, timeout=5)            # no lanza


def test_el_codigo_no_usa_cache_get_ni_set_directo():
    """cache.get()/cache.set() lanzan si Redis no está: hay que usar cache.leer()/cache.guardar()."""
    malos = []
    for patron in ("*.py", "auth/*.py", "tasks/*.py"):
        for ruta in glob.glob(os.path.join(RAIZ, patron)):
            if os.path.basename(ruta) == "cache.py":
                continue
            for n, linea in enumerate(open(ruta, encoding="utf-8"), 1):
                if re.search(r"(?<![\w.])cache\.(get|set|delete)\(", linea) and not linea.strip().startswith("#"):
                    malos.append(f"{os.path.relpath(ruta, RAIZ)}:{n}")
    assert not malos, "Usá cache_leer/cache_guardar (cache.py): " + ", ".join(malos)

"""
Mide cuánto cuesta sincronizar una cuenta: llamadas a Mercado Libre y Mercado Pago (cuáles y cuántas), tiempo total y conexiones a la base.
Sirve para calcular cuántas cuentas aguanta el servidor y para ver qué optimizar con datos en vez de adivinar.

    python medir_sync.py <usuario_id> <cuenta_id>

Corre una sincronización completa NORMAL de esa cuenta (la misma que hace el scheduler cada 4 minutos) dos veces: la primera suele traer datos nuevos y la
segunda es el costo "de régimen", el que se paga en cada ciclo. Para medir producción (donde la base está a pocos milisegundos y los tiempos son los reales):

    fly ssh console -a corecore -C "python medir_sync.py <usuario_id> <cuenta_id>"
"""
import collections
import re
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

import db  # noqa: E402
import meli_http  # noqa: E402
import sincronizador  # noqa: E402

CICLO_SEGUNDOS = 240          # el scheduler sincroniza cada 4 minutos
EN_PARALELO = 2               # scheduler.SYNC_CUENTAS_EN_PARALELO

llamadas, tiempos, lock, conexiones = collections.Counter(), [], threading.Lock(), {"n": 0}


def _envolver(metodo, original):
    def f(url, **kw):
        t0 = time.time()
        r = original(url, **kw)
        clave = re.sub(r"\d{6,}", "N", url.split("?")[0].replace("https://api.mercadolibre.com", "ML").replace("https://api.mercadopago.com", "MP"))
        with lock:
            llamadas[f"{metodo} {clave}"] += 1
            tiempos.append(time.time() - t0)
        return r
    return f


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    usuario_id, cuenta_id = int(sys.argv[1]), int(sys.argv[2])
    for m in ("get", "put", "post"):
        setattr(meli_http, m, _envolver(m.upper(), getattr(meli_http, m)))
    original = db.conexion_usuario

    def contada(*a, **k):
        conexiones["n"] += 1
        return original(*a, **k)
    db.conexion_usuario = contada

    duracion = 0
    for corrida in (1, 2):
        llamadas.clear()
        tiempos.clear()
        conexiones["n"] = 0
        t0 = time.time()
        sincronizador.sincronizar_todo(usuario_id, cuenta_id)
        duracion = time.time() - t0
        total = sum(llamadas.values())
        print(f"\n=== Corrida {corrida}: {duracion:.1f} s | {total} llamadas a APIs (media {sum(tiempos) / max(len(tiempos), 1) * 1000:.0f} ms) | {conexiones['n']} conexiones a la base")
        for clave, n in llamadas.most_common(10):
            print(f"   {n:4d}  {clave}")
    por_ciclo = int(CICLO_SEGUNDOS / duracion * EN_PARALELO) if duracion else 0
    print(f"\nA {duracion:.0f} s por cuenta, {EN_PARALELO} en paralelo, entran unas {por_ciclo} cuentas en un ciclo de 4 minutos sin atrasarse.")
    print(f"Llamadas por hora a Mercado Libre/Pago por cuenta: {int(sum(llamadas.values()) * 3600 / CICLO_SEGUNDOS)}")


if __name__ == "__main__":
    main()

"""
Antirrebote para las notificaciones de Mercado Libre.

Una venta dispara varias notificaciones seguidas (orden, pago, envío...) y un ítem muy movido, decenas. Cada una pediría la misma
sincronización a la API de Mercado Libre. Con el antirrebote, la primera corre enseguida y las que llegan dentro del intervalo se
juntan en UNA sola corrida al final del intervalo: no se pierde ninguna novedad y no se multiplican las llamadas.

Las claves llevan siempre el cuenta_id (ver el resto del proyecto): nada se comparte entre cuentas.
"""
import threading
import time


class Antirrebote:
    def __init__(self, intervalo_segundos=15):
        self.intervalo = intervalo_segundos
        self._lock = threading.Lock()
        self._estado = {}      # clave -> {"ultimo": instante de la última corrida, "agendada": bool}

    def ejecutar(self, clave, funcion):
        """Corre `funcion()` ya, o la deja agendada una sola vez para cuando se cumpla el intervalo. Nunca levanta una excepción."""
        with self._lock:
            ahora = time.monotonic()
            if len(self._estado) > 5000:        # limpieza: las claves viejas ya no frenan nada
                self._estado = {k: v for k, v in self._estado.items() if v["agendada"] or ahora - v["ultimo"] < self.intervalo}
            estado = self._estado.get(clave)
            if estado is None or (not estado["agendada"] and ahora - estado["ultimo"] >= self.intervalo):
                self._estado[clave] = {"ultimo": ahora, "agendada": False}
                correr_ya = True
            elif estado["agendada"]:
                return False                    # ya hay una corrida esperando: esta novedad entra en esa
            else:
                estado["agendada"] = True
                demora = self.intervalo - (ahora - estado["ultimo"])
                correr_ya = False
        if correr_ya:
            self._correr(funcion)
            return True
        temporizador = threading.Timer(demora, self._correr_agendada, args=(clave, funcion))
        temporizador.daemon = True
        temporizador.start()
        return True

    def _correr_agendada(self, clave, funcion):
        with self._lock:
            self._estado[clave] = {"ultimo": time.monotonic(), "agendada": False}
        self._correr(funcion)

    @staticmethod
    def _correr(funcion):
        try:
            funcion()
        except Exception as e:
            print(f"[Antirrebote] ❌ Error en la tarea: {e}")

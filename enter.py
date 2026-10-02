import datetime
import time
import pyautogui

HORA_OBJETIVO = 7
MINUTO_OBJETIVO = 0

print(f"Script iniciado. Esperando a las {HORA_OBJETIVO:02d}:{MINUTO_OBJETIVO:02d} AM para presionar Enter...")

while True:
    ahora = datetime.datetime.now()

    # Verifica si ya son las 07:00 AM (o un margen de segundos posteriores si hubo delay)
    if ahora.hour == HORA_OBJETIVO and ahora.minute == MINUTO_OBJETIVO:
        print(f"Hora alcanzada ({ahora.strftime('%H:%M:%S')}). Presionando Enter...")
        pyautogui.press('enter')
        print("¡Enter presionado con éxito!")
        break

    # Revisa cada 1 segundo para no consumir CPU
    time.sleep(1)
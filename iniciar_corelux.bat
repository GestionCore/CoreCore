@echo off
REM ============================================================
REM  CoreLux — arranque rápido (PROVISORIO)
REM  Abre cada proceso en su propia ventana, para poder ver los
REM  logs de cada uno por separado. Cerrá las ventanas para parar
REM  todo (o Ctrl+C en cada una).
REM
REM  Antes de usarlo, revisá las dos rutas de la sección
REM  CONFIGURAR que están justo abajo — están puestas como
REM  ejemplo, con la carpeta de este proyecto en particular.
REM ============================================================

REM ----------------- CONFIGURAR -----------------
set RUTA_PROYECTO=C:\Users\clona\Desktop\Integrador MELI Alpha v0.0\Integrador\CoreLux-SaaS
REM -----------------------------------------------

echo Iniciando CoreLux...
echo.

REM 1) La app de Flask, con el entorno virtual activado
start "CoreLux - app.py" cmd /k "cd /d "%RUTA_PROYECTO%" && call venv\Scripts\activate.bat && python app.py"

REM Un respiro para que Flask levante antes de que ngrok intente
REM apuntarle al puerto 5000.
timeout /t 3 /nobreak >nul

REM 2) El túnel de ngrok
start "CoreLux - ngrok" cmd /k "ngrok http 5000"

REM 3) Puente de WhatsApp — todavía no está construido en CoreLux
REM    (es parte del roadmap, no un olvido). Cuando exista, esta
REM    línea se descomenta y se ajusta la ruta:
REM start "CoreLux - WhatsApp Bridge" cmd /k "cd /d "%RUTA_PROYECTO%\whatsapp-bridge" && node index.js"

echo.
echo Se abrieron las ventanas de app.py y ngrok.
echo Esta ventana ya puede cerrarse — las otras dos siguen corriendo solas.
pause

@echo off
REM ============================================================
REM  CoreLux — arranque en tu PC
REM
REM  Abre la app y ngrok, cada uno en su ventana CMD. Cerrá las ventanas para parar todo.
REM  Ya no hace falta Redis ni Celery: las tareas periódicas (sincronización cada 4 minutos, etc.) corren dentro de la propia app,
REM  igual que en producción.
REM ============================================================

REM ----------------- CONFIGURAR -----------------
set RUTA_PROYECTO=C:\Users\clona\Desktop\Integrador MELI Alpha v0.0\Integrador\CoreLux-SaaS
REM -----------------------------------------------

echo.
echo ====================================================
echo   CoreLux — Iniciando servicios
echo ====================================================
echo.

REM ── 1) Flask app (con Waitress) ──────────────────────────────────────────
echo [1/2] Iniciando Flask + Waitress...
start "CoreLux - App (Waitress)" cmd /k "cd /d "%RUTA_PROYECTO%" && call venv\Scripts\activate.bat && python app.py"

REM Pausa para que Flask levante antes de que ngrok apunte al puerto 5000
timeout /t 4 /nobreak >nul

REM ── 2) ngrok ─────────────────────────────────────────────────────────────
echo [2/2] Iniciando ngrok...
start "CoreLux - ngrok" cmd /k "ngrok http 5000"

echo.
echo ====================================================
echo   Servicios levantando en sus ventanas propias.
echo.
echo   Flask:       http://localhost:5000
echo   ngrok:       ver ventana "CoreLux - ngrok"
echo.
echo   Para ver errores de produccion: dashboard Sentry
echo.
echo   Esta ventana puede cerrarse.
echo ====================================================
echo.
pause

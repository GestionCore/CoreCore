@echo off
REM ============================================================
REM  CoreLux — arranque completo (Fase 0: Infraestructura)
REM
REM  Abre cada proceso en su propia ventana CMD.
REM  Cerrá las ventanas para parar todo (o Ctrl+C en cada una).
REM
REM  REQUISITOS:
REM  -----------
REM  1. Redis corriendo (local o cloud):
REM       Opción A — Local Windows: Memurai https://www.memurai.com/
REM                  (o Redis para Windows: github.com/tporadowski/redis)
REM       Opción B — Nube gratis: Upstash https://upstash.com/
REM                  (conseguís una REDIS_URL para poner en .env)
REM
REM  2. .env configurado con REDIS_URL (además de las vars de siempre)
REM
REM  Sin Redis: la app igual arranca. Las tareas periódicas caen a
REM  APScheduler (en el mismo proceso) y los webhooks a daemon threads.
REM  Funciona para desarrollo básico, no para producción.
REM ============================================================

REM ----------------- CONFIGURAR -----------------
set RUTA_PROYECTO=C:\Users\clona\Desktop\Integrador MELI Alpha v0.0\Integrador\CoreLux-SaaS
REM -----------------------------------------------

echo.
echo ====================================================
echo   CoreLux — Iniciando servicios
echo ====================================================
echo.

REM ── 1) Celery Worker ────────────────────────────────────────────────────
REM    --pool=solo es necesario en Windows (multiprocessing limitado).
REM    En Linux de producción: quitar --pool=solo y usar --concurrency=4
echo [1/5] Iniciando Celery Worker...
start "CoreLux - Celery Worker" cmd /k "cd /d "%RUTA_PROYECTO%" && call venv\Scripts\activate.bat && celery -A celery_app worker --pool=solo --loglevel=info --concurrency=1"

REM Pausa para que el worker levante antes de que Beat empiece a encolar tareas
timeout /t 4 /nobreak >nul

REM ── 2) Celery Beat (scheduler periódico) ────────────────────────────────
echo [2/5] Iniciando Celery Beat...
start "CoreLux - Celery Beat" cmd /k "cd /d "%RUTA_PROYECTO%" && call venv\Scripts\activate.bat && celery -A celery_app beat --loglevel=info"

REM Pausa para que Beat quede estable antes de Flask
timeout /t 2 /nobreak >nul

REM ── 3) Flask app (con Waitress) ──────────────────────────────────────────
echo [3/5] Iniciando Flask + Waitress...
start "CoreLux - App (Waitress)" cmd /k "cd /d "%RUTA_PROYECTO%" && call venv\Scripts\activate.bat && python app.py"

REM Pausa para que Flask levante antes de que ngrok apunte al puerto 5000
timeout /t 4 /nobreak >nul

REM ── 4) ngrok ─────────────────────────────────────────────────────────────
echo [4/5] Iniciando ngrok...
start "CoreLux - ngrok" cmd /k "ngrok http 5000"

REM ── 5) Puente de WhatsApp (comentado — pendiente de construcción) ─────────
REM start "CoreLux - WhatsApp Bridge" cmd /k "cd /d "%RUTA_PROYECTO%\whatsapp-bridge" && node index.js"

echo.
echo ====================================================
echo   Servicios levantando en sus ventanas propias.
echo.
echo   Flask:       http://localhost:5000
echo   Celery:      ver ventana "CoreLux - Celery Worker"
echo   ngrok:       ver ventana "CoreLux - ngrok"
echo.
echo   Para ver errores de produccion: dashboard Sentry
echo   Para gestionar colas:  celery -A celery_app inspect active
echo.
echo   Esta ventana puede cerrarse.
echo ====================================================
echo.
pause

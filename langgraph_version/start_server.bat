@echo off
rem ============================================================
rem  AI resume agent web server launcher
rem  Starts uvicorn in background, logs to web_out.log / web_err.log
rem  Checks port first, then waits for health check to pass
rem ============================================================
cd /d "%~dp0"

set "PORT=8000"
set "PYEXE=%~dp0..\.venv\Scripts\python.exe"

rem ---- 1. Port check: already in use means a service may be running ----
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [ERROR] Port %PORT% is already in use. A service may already be running.
    echo Check http://127.0.0.1:%PORT%/api/health or stop the old process first.
    pause
    exit /b 1
)

rem ---- 2. Offline env vars (load models locally, avoid HF network stalls) ----
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set HF_HUB_DISABLE_TELEMETRY=1
set HF_HUB_DISABLE_PROGRESS_BARS=1
set MOCK_LLM=0

rem ---- 3. Start uvicorn in background (redirect to log files) ----
start "aiagent-web" /min cmd /c ""%PYEXE%" -m uvicorn web_app:app --host 127.0.0.1 --port %PORT% >> "%~dp0web_out.log" 2>> "%~dp0web_err.log""

rem ---- 4. Wait for health check (max 60 seconds) ----
echo Waiting for service readiness (first start preheats models, may take 10-60s)...
set /a tries=0
:wait_health
set /a tries=tries+1
if %tries% gtr 60 goto timeout
curl -sf http://127.0.0.1:%PORT%/api/health >nul 2>nul
if not errorlevel 1 goto ready
timeout /t 1 /nobreak >nul
goto wait_health

:ready
echo [OK] Service ready: http://127.0.0.1:%PORT%
exit /b 0

:timeout
echo [ERROR] Health check did not pass within 60s. Check web_err.log.
exit /b 1

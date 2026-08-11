@echo off
rem AI resume agent web server launcher (detached, logs to web_out.log / web_err.log)
cd /d "%~dp0"
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set HF_HUB_DISABLE_TELEMETRY=1
set HF_HUB_DISABLE_PROGRESS_BARS=1
set MOCK_LLM=0
"%~dp0..\.venv\Scripts\python.exe" -m uvicorn web_app:app --host 127.0.0.1 --port 8000 >> "%~dp0web_out.log" 2>> "%~dp0web_err.log"

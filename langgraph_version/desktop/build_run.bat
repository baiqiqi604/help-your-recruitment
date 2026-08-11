@echo off
rem PyInstaller build script (run by scheduled task, no hardcoded paths)
cd /d "%~dp0.."
echo [start] %date% %time% >> desktop\build_run.log
"%~dp0..\..\.venv\Scripts\pyinstaller.exe" desktop\build.spec --noconfirm --distpath desktop\dist --workpath desktop\build >> desktop\build_run.log 2>&1
echo [exitcode] %ERRORLEVEL% %date% %time% >> desktop\build_run.log

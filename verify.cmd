@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\verify_setup.py" %*
set "deerExit=%ERRORLEVEL%"
echo.
pause
exit /b %deerExit%

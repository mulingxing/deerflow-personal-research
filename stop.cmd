@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
set "deerExit=%ERRORLEVEL%"
if not "%deerExit%"=="0" pause
exit /b %deerExit%

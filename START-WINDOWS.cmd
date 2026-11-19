@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [AutumnGenLogin] Creating Python 3.12 environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :fail
)
echo [AutumnGenLogin] Synchronizing dependencies for existing and new installations...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 goto :fail
exit /b 0
:fail
echo.
echo ERROR: Dependency install or application startup failed. Check Python 3.12, connectivity, and run START-WINDOWS.cmd --doctor.
if /I "%CI%"=="true" exit /b 1
pause
exit /b 1

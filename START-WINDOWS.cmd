@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [AutumnGenLogin] Creating Python 3.12 environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :fail
exit /b 0
:fail
echo.
echo ERROR: Install Python 3.12 from python.org, verify internet connectivity, then try again.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :fail
".venv\Scripts\pyinstaller.exe" --clean --noconfirm --onefile --windowed --name AutumnGenLogin --collect-all playwright --collect-all keyring main.py
if errorlevel 1 goto :fail
powershell -NoProfile -Command "$p = Start-Process -FilePath (Join-Path (Get-Location) 'dist\AutumnGenLogin.exe') -ArgumentList '--self-check' -Wait -PassThru; if ($p.ExitCode -ne 0) { exit 1 }"
if errorlevel 1 goto :fail
echo.
echo SUCCESS! Output: %~dp0dist\AutumnGenLogin.exe
pause
exit /b 0
:fail
echo.
echo ERROR: Build failed. Check Python 3.12, network access and logs above.
pause
exit /b 1

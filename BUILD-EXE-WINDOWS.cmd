@echo off
setlocal
REM This guard is intentional: no EXE build before fully verified feature parity.
echo =========================================================
echo AUTUMNGENLOGIN RELEASE HOLD
 echo Unverified GenLogin/Titan feature parity and acceptance gates.
echo EXE creation is disabled by the explicit user release policy.
echo See docs\RELEASE_GATES.md for the conditions to lift this gate.
echo =========================================================
exit /b 3

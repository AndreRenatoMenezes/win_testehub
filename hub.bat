@echo off
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :admin
) else (
    goto :elevate
)

:elevate

echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
"%temp%\getadmin.vbs"
del "%temp%\getadmin.vbs"
exit /B

:admin
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Unrestricted -Scope CurrentUser -Force; C:\TesteHub\hub.ps1"
pause
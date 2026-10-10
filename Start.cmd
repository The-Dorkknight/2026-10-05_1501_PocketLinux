@echo off
rem Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
rem Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
rem PocketLinux 0.3.0-wip - double-click to start. Installs Python (once) if missing.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0src\main.py" & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0src\main.py" & exit /b 0)
echo Python was not found. Installing Python 3.12 with winget (approve any prompt)...
winget install --exact --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo If that succeeded, close this window and double-click Start.cmd again.
pause

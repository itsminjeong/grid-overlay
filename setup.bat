@echo off
cd /d "%~dp0"
set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  ) else (
    echo Python 3.12 or newer was not found.
    echo Install Python and select Add Python to PATH.
    pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  "%PYTHON_CMD%" -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed.
  pause
  exit /b 1
)
echo Setup complete. Run run.bat.
pause

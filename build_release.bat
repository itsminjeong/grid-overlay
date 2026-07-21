@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] Virtual environment was not found.
  echo Run setup.bat first, then run this file again.
  pause
  exit /b 1
)

echo [1/4] Installing PyInstaller...
"%PYTHON%" -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo [ERROR] PyInstaller installation failed.
  echo Check the internet connection or company security policy.
  pause
  exit /b 1
)

echo [2/4] Building the portable Windows application...
"%PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onedir --noupx --name GridOverlay main.py
if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

echo [3/4] Adding usage and license notices...
copy /y "SHARING_GUIDE.txt" "dist\GridOverlay\USAGE.txt" >nul
copy /y "THIRD_PARTY_NOTICES.txt" "dist\GridOverlay\THIRD_PARTY_NOTICES.txt" >nul

echo [4/4] Creating ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '.\dist\GridOverlay' -DestinationPath '.\GridOverlay-Windows-v0.1.zip' -Force"
if errorlevel 1 (
  echo [ERROR] ZIP creation failed.
  pause
  exit /b 1
)

echo.
echo Build complete:
echo %CD%\GridOverlay-Windows-v0.1.zip
echo.
echo Share this ZIP file. Users should extract it and run GridOverlay.exe.
pause
endlocal

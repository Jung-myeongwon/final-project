@echo off
cd /d "%~dp0"

echo =============================================
echo  TasteLab Desktop Build
echo  Output: dist\TasteLab\TasteLab.exe
echo =============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.12 and add to PATH.
  pause
  exit /b 1
)

echo [1/3] Installing packages...
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

echo [2/3] Running PyInstaller - may take several minutes...
python -m PyInstaller --noconfirm tastelab_desktop.spec
if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

echo [3/3] Done.
echo.
echo Folder: %~dp0dist\TasteLab
echo Run:    %~dp0dist\TasteLab\TasteLab.exe
echo.
echo Copy the whole dist\TasteLab folder to another PC.
echo Double-click TasteLab.exe - no Python required.
echo.
pause

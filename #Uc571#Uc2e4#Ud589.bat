@echo off
cd /d "%~dp0"

echo =====================================
echo Movie and Music Recommender - Start
echo First run installs required packages.
echo =====================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Install Python 3.12 and check "Add Python to PATH".
  pause
  exit /b 1
)

echo Installing packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Package install failed.
  pause
  exit /b 1
)

echo.
echo Starting server. Do not close this window.
echo Browser opens at http://127.0.0.1:8000 in a few seconds.
echo.

start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:8000"
python -m uvicorn main:app --host 127.0.0.1 --port 8000

pause

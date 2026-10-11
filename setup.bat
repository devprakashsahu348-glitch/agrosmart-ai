@echo off
REM AgroSmart AI - one-time setup (needs internet ONCE, unless you use the offline "wheels" folder).
setlocal
cd /d "%~dp0"
echo.
echo === AgroSmart AI setup ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from python.org and tick "Add Python to PATH".
  pause & exit /b 1
)
if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>nul
if exist wheels (
  echo Installing from the local "wheels" folder - no internet needed...
  pip install --no-index --find-links wheels -r requirements.txt
) else (
  echo Installing packages from the internet...
  pip install -r requirements.txt
)
if errorlevel 1 ( echo Package installation failed. See README.md - Troubleshooting. & pause & exit /b 1 )
echo.
echo Training the machine-learning models (about 1 minute)...
python train_models.py
if errorlevel 1 ( echo Model training failed. & pause & exit /b 1 )
echo.
echo Setup finished. Double-click run.bat to start AgroSmart AI.
pause

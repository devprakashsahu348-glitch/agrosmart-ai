@echo off
REM AgroSmart AI - start the app (works with NO internet connection).
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
REM open the browser a few seconds after the server starts
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"
python app.py
pause

@echo off
set PYTHONUTF8=1
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto failed
:dependencies
".venv\Scripts\python.exe" -c "import pptx, PIL, pypdf, fontTools" >nul 2>nul
if not errorlevel 1 goto launch
echo Installing report libraries. This is needed once.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
".venv\Scripts\python.exe" server.py --open
goto end
:failed
echo Setup failed. Install Python 3.10 or newer and check your internet connection.
:end
pause

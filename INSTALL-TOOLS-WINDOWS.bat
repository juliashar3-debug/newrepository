@echo off
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 tools\install_tools.py
) else (
  python tools\install_tools.py
)
if errorlevel 1 (
  echo Installation failed. See the error above.
) else (
  echo Tools installed. Use START-WINDOWS.bat to open the site.
)
pause

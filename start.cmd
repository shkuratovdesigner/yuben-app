@echo off
rem Double-click to install (first time) and start YuBen.
rem Same as "py yuben.py start" from a terminal.
setlocal
cd /d "%~dp0"

rem Prefer the py launcher: "python" may be the Microsoft Store stub, which
rem exists on PATH but only opens the Store.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 yuben.py start
  goto done
)
python --version >nul 2>nul
if %errorlevel%==0 (
  python yuben.py start
  goto done
)
echo Python is not installed. Get Python 3.10+ from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH", then double-click start.cmd again.
pause
exit /b 1

:done
if errorlevel 1 pause

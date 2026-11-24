@echo off
rem Keshin2D: open the avatar viewer in the browser (Google Chrome if installed, otherwise the default browser).
rem Usage: start.bat [--model NAME] [--port N]   (double-click opens the bundled model "kurage02")
rem This file is ASCII only: cmd.exe misreads non-ASCII text in a .bat file.
cd /d "%~dp0"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% tools\serve.py %*
if errorlevel 1 pause
goto :eof
:nopython
echo Python 3.8 or later was not found.
echo Install it from https://www.python.org/downloads/ and run this file again.
pause

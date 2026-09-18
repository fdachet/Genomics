@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  ctDNA pipeline - Windows GUI dependency installer
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    echo Install a standard 64-bit Python 3 distribution for Windows first.
    echo The standard python.org installer includes Tk/Tkinter.
    pause
    exit /b 1
)

python --version
if errorlevel 1 goto :failed

python -c "import tkinter; print('Tkinter: OK')"
if errorlevel 1 (
    echo ERROR: Tkinter is not available in this Windows Python installation.
    pause
    exit /b 1
)

echo.
echo Installing packages required to open the Windows GUIs...
python -m pip install --user --upgrade -r requirements_windows_gui.txt
if errorlevel 1 goto :failed

echo.
echo Verifying Windows GUI imports...
python -c "import pandas,numpy,matplotlib,networkx,tkinter; print('Windows GUI imports: OK')"
if errorlevel 1 goto :failed

echo.
echo Windows GUI dependencies installed successfully.
pause
exit /b 0

:failed
echo.
echo Installation or verification failed.
pause
exit /b 1

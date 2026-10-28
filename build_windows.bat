@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
echo === LiteynyiTseh PRO - Windows EXE builder ===
echo Requires Windows 10/11 64-bit and internet for first setup.
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  )
)
if not defined PYTHON_CMD (
  echo Python 3.12 x64 not found.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Install Python 3.12 x64 from https://www.python.org/downloads/
    goto :failure
  )
  echo Installing Python 3.12 using Windows Package Manager...
  winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto :failure
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  ) else (
    echo Restart the terminal and run build_windows.bat again.
    goto :failure
  )
)
echo Using %PYTHON_CMD%
if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :failure
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failure
".venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.12,<7"
if errorlevel 1 goto :failure
".venv\Scripts\python.exe" -m compileall -q core gui data import_export tests
if errorlevel 1 goto :failure
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
  echo NOTE: tests failed. Build cancelled to avoid shipping unchecked calculations.
  goto :failure
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name LiteynyiTsehPRO --icon "assets\icons\app_icon.ico" --add-data "data;data" --add-data "assets;assets" main.py
if errorlevel 1 goto :failure
if not exist "dist\LiteynyiTsehPRO\LiteynyiTsehPRO.exe" goto :failure
echo.
echo SUCCESS: dist\LiteynyiTsehPRO\LiteynyiTsehPRO.exe
echo Copy the WHOLE dist\LiteynyiTsehPRO folder to the target PC.
echo Python is NOT needed to run the built application.
pause
exit /b 0
:failure
echo Build failed. Read the error above and see WINDOWS_BUILD.md.
pause
exit /b 1

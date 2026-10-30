@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto :failure
chcp 65001 >nul
echo === LiteynyiTseh PRO - Windows x64 EXE builder ===
echo Windows 10/11 x64, Python 3.12 x64, internet on first build.
echo.

rem NEVER install PySide6 into .venv under the extracted GitHub folder.
rem Qt QML contains long filenames and Windows MAX_PATH can reject them.
rem Use a short temporary path for venv, PyInstaller work and output.
set "BUILD_ROOT=%TEMP%\FPRO"
if defined FOUNDRY_BUILD_HOME set "BUILD_ROOT=%FOUNDRY_BUILD_HOME%"
set "VENV_DIR=%BUILD_ROOT%\venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "WORK_DIR=%BUILD_ROOT%\work"
set "DIST_DIR=%BUILD_ROOT%\dist"
set "ARCHIVE_OUT=%CD%\LiteynyiTsehPRO-Windows-x64.zip"
if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"
if errorlevel 1 goto :failure

echo Source project: %CD%
echo Short build path: %BUILD_ROOT%
echo Old .venv folder in project is NOT used.
echo.

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)
if not defined PYTHON_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  )
)
if not defined PYTHON_CMD (
  echo Python 3.12 x64 not found.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Please install Python 3.12 x64 from https://www.python.org/downloads/
    goto :failure
  )
  echo Installing Python 3.12 x64 using Windows Package Manager...
  winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto :failure
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  ) else (
    echo Restart this terminal and run build_windows.bat again.
    goto :failure
  )
)

echo Using %PYTHON_CMD%
if not exist "%VENV_PY%" (
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 goto :failure
)
"%VENV_PY%" -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip
if errorlevel 1 goto :pip_failure
"%VENV_PY%" -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt "pyinstaller>=6.12,<7" pytest pytest-timeout
if errorlevel 1 goto :pip_failure

echo.
echo === Checking calculations before packaging ===
"%VENV_PY%" -m compileall -q core gui data import_export tests
if errorlevel 1 goto :failure
set "QT_QPA_PLATFORM=offscreen"
rem Windows offscreen Qt startup can be slower than Linux CI, especially
rem when PySide6 initializes many department tabs for each GUI regression.
rem Keep ALL tests enabled; allow a bounded 90 seconds per individual test.
"%VENV_PY%" -m pytest -q --timeout=90
if errorlevel 1 (
  echo Tests failed. Build cancelled: do not distribute unchecked calculations.
  goto :failure
)

echo.
echo === Bundling Windows executable to SHORT path ===
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name LiteynyiTsehPRO --workpath "%WORK_DIR%" --distpath "%DIST_DIR%" --icon "assets\icons\app_icon.ico" --add-data "data;data" --add-data "assets;assets" --add-data "docs;docs" --add-data "examples;examples" main.py
if errorlevel 1 goto :failure
if not exist "%DIST_DIR%\LiteynyiTsehPRO\LiteynyiTsehPRO.exe" goto :failure

echo.
echo === Creating ZIP for easy transfer to new PC ===
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; Compress-Archive -LiteralPath (Join-Path $env:DIST_DIR 'LiteynyiTsehPRO') -DestinationPath $env:ARCHIVE_OUT -Force"
if errorlevel 1 goto :zip_failure
if not exist "%ARCHIVE_OUT%" goto :zip_failure
echo.
echo SUCCESS
echo Windows executable folder: %DIST_DIR%\LiteynyiTsehPRO
echo Portable archive: %ARCHIVE_OUT%
echo On another PC, unpack the ZIP and run LiteynyiTsehPRO.exe.
echo Python is NOT required on the target PC.
goto :success

:pip_failure
echo.
echo ERROR installing dependencies (PySide6 / pip).
echo The virtual environment is at: %VENV_DIR%
echo If corrupted, close terminals and remove ONLY that venv folder.
echo If the temporary path is unusually long, open cmd and use:
echo   set FOUNDRY_BUILD_HOME=F:\FPRO
echo   call build_windows.bat
echo See WINDOWS_BUILD.md for details.
goto :failure

:zip_failure
echo.
echo EXE built, but ZIP could not be created.
echo Use the entire folder: %DIST_DIR%\LiteynyiTsehPRO
goto :failure

:success
if not defined CI pause
exit /b 0

:failure
echo.
echo Build failed. Read the messages above and WINDOWS_BUILD.md.
if not defined CI pause
exit /b 1

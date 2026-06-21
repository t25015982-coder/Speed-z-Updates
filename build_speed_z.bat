@echo off
REM SPEED-Z Launcher Build Pipeline v1.0.7
REM One-shot compilation to single executable

echo [*] SPEED-Z Launcher Build Pipeline v1.0.7
echo.

REM Verify Python and PyInstaller
python --version >nul 2>&1 || (
    echo [X] Python not found in PATH
    exit /b 1
)

pyinstaller --version >nul 2>&1 || (
    echo [*] Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
echo [*] Cleaning build artifacts...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

REM Compile to single EXE
echo [*] Compiling to single executable...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "SPEED-Z-Launcher" ^
    --icon=NONE ^
    --add-data "speed_z_models.py;." ^
    --add-data "speed_z_core.py;." ^
    --add-data "speed_z_config.py;." ^
    --add-data "speed_z_io.py;." ^
    --add-data "speed_z_logging.py;." ^
    --add-data "speed_z_errors.py;." ^
    speed_z_launcher.py

if %ERRORLEVEL% NEQ 0 (
    echo [X] Build failed
    exit /b 1
)

echo.
echo [+] Build complete: dist\SPEED-Z-Launcher.exe
echo [*] Version: 1.0.7
echo [*] Theme: Crimson (Red/Gold)
echo [*] Features: No expiry, Webhook, Executor UI
pause

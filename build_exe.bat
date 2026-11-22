@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\pyinstaller.exe" (
    echo PyInstaller is not installed in the venv.
    exit /b 1
)

if not exist "assets\source\Program.png" (
    echo Missing icon source: assets\source\Program.png
    exit /b 1
)

"venv\Scripts\python.exe" tools\sync_program_icon.py
if errorlevel 1 exit /b 1

"venv\Scripts\pyinstaller.exe" --noconfirm --clean MachineCpkReporter.spec

@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\pyinstaller.exe" (
    echo PyInstaller is not installed in the venv.
    exit /b 1
)

if not exist "Icon\Program.png" (
    echo Missing icon source: Icon\Program.png
    exit /b 1
)

"venv\Scripts\python.exe" tools\sync_program_icon.py
if errorlevel 1 exit /b 1

"venv\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name MachineCpkReporter ^
  --icon assets\program_source.ico ^
  --add-data Icon\Program.png;Icon ^
  --add-data assets\program_source.ico;assets ^
  --add-data assets\program_source_256.png;assets ^
  --collect-data matplotlib ^
  --collect-data reportlab ^
  --hidden-import openpyxl ^
  desktop_main.py

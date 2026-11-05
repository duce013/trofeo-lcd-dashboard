@echo off
rem Builds dist\TrofeoLCD.exe (one shareable file). Needs: .venv with requirements + pyinstaller + libusb-package.
cd /d "%~dp0"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name TrofeoLCD ^
  --paths src --paths dash ^
  --icon dash\duce.ico --add-data "dash\duce.ico;." --add-data "dash\duce.png;." ^
  --add-data "vdd;vdd" --add-data "vendor\lhm;lhm" ^
  --collect-binaries libusb_package --hidden-import libusb_package ^
  --collect-data customtkinter --hidden-import customtkinter ^
  --hidden-import hw_info --hidden-import media --hidden-import settings_ui --hidden-import cv2 --hidden-import clr --collect-all pythonnet --collect-all clr_loader ^
  --exclude-module stats_provider --exclude-module panel ^
  src\app.py

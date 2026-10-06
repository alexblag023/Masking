@echo off
rem Сборка masking-service.exe (запускать на Windows, нужен Python 3.10+)
python -m pip install -r requirements-dev.txt || exit /b 1
python -m PyInstaller --noconfirm --clean masking-service.spec || exit /b 1
echo Готово: dist\masking-service.exe

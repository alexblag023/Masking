@echo off
rem Portable-сборка masking-service для Windows. Требуется Python 3.10+.
rem Результат: dist\masking-service\ — папка с masking-service.exe и _internal\.
rem Копируйте всю папку целиком; data\ создастся рядом с exe при первом запуске.

python -m pip install -r requirements-dev.txt || exit /b 1
python -m PyInstaller --noconfirm --clean masking-service.spec || exit /b 1
echo.
echo Готово: dist\masking-service\masking-service.exe
echo Папку dist\masking-service можно скопировать и запускать с флешки.

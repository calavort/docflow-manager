@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo  DOCFLOW MANAGER - INSTALACAO PYTHON
echo ========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m pip install --upgrade pip
    py -3 -m pip install -r requirements.txt
) else (
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo Falha ao instalar as bibliotecas.
    pause
    exit /b 1
)

echo.
echo Bibliotecas instaladas com sucesso.
echo Agora execute DocFlow_Manager.pyw ou crie o atalho do Menu Iniciar.
pause

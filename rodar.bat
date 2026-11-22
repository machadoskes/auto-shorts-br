@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Auto Shorts - trabalhando (nao feche esta janela)
if not exist logs mkdir logs
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Ambiente nao instalado. Rode o instalar.bat primeiro.
  exit /b 1
)
echo === Auto Shorts: gerando e publicando o video deste horario ===
echo O andamento aparece abaixo e tambem fica salvo em logs\
echo.
".venv\Scripts\python.exe" main.py %* 2>> "logs\erros.txt"
echo.

echo Concluido. Esta janela fecha sozinha em 30 segundos.
timeout /t 30 >nul
exit /b 0

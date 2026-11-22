@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Gerar carrossel (sem publicar)
echo === Gerando um CARROSSEL com as noticias do dia (nao publica) ===
echo.
".venv\Scripts\python.exe" main.py --carrossel --sem-publicar
echo.
echo Pronto. Os slides ficam na pasta "saida" (a mais recente). Publique com 3_publicar_ultimo.bat
pause

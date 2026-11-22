@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Gerar novo video (sem publicar)
echo === Gerando um NOVO video a partir das noticias do dia (nao publica) ===
echo.
".venv\Scripts\python.exe" main.py --sem-publicar
echo.
echo Pronto. O video fica na pasta "saida" (a mais recente).
pause

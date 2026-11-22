@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Montar biblioteca de cenas oficiais
echo === Biblioteca de cenas (midia\trailers, midia\videos, midia\imagens) ===
echo 1. Baixa os videos listados no config.json (secao "trailers"), se houver
echo 2. Corta em cenas curtas e pede ao Gemini para etiquetar cada uma
echo Rode de novo sempre que colocar um trailer novo em midia\trailers.
echo.
".venv\Scripts\python.exe" main.py --biblioteca
echo.
pause

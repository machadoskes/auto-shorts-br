@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Refazer o ultimo video
set "ULTIMO="
for /f "delims=" %%d in ('dir /b /ad /o-n "saida"') do if not defined ULTIMO set "ULTIMO=%%d"
if not defined ULTIMO ( echo Nenhum video em "saida". & pause & exit /b 1 )
echo === Refazendo voz e video de: %ULTIMO% ===
echo (mesmo roteiro; nao publica)
echo.
".venv\Scripts\python.exe" main.py --refazer "saida\%ULTIMO%"
echo.
echo Pronto. Abra: saida\%ULTIMO%\reels.mp4
pause

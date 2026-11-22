@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Publicar o ultimo video (Instagram + TikTok)
set "ULTIMO="
for /f "delims=" %%d in ('dir /b /ad /o-n "saida"') do if not defined ULTIMO set "ULTIMO=%%d"
if not defined ULTIMO ( echo Nenhum video em "saida". & pause & exit /b 1 )
echo === PUBLICAR NO INSTAGRAM (e enviar rascunho ao TikTok) ===
echo Video:   saida\%ULTIMO%\reels.mp4
echo Legenda:
echo ----------------------------------------
type "saida\%ULTIMO%\legenda.txt"
echo.
echo ----------------------------------------
set /p RESP=Publicar este video agora? (S/N):
if /i not "%RESP%"=="S" ( echo Nada foi publicado. & pause & exit /b 0 )
".venv\Scripts\python.exe" main.py --publicar "saida\%ULTIMO%"
echo.
pause

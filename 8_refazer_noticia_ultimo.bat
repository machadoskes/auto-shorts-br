@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Refazer o roteiro da ultima noticia e publicar
set "ULTIMO="
for /f "delims=" %%d in ('dir /b /ad /o-n "saida" ^| findstr /v /i "carrossel"') do if not defined ULTIMO set "ULTIMO=%%d"
if not defined ULTIMO ( echo Nenhum video em "saida". & pause & exit /b 1 )
echo === REFAZER COM ROTEIRO COMPLETO E PUBLICAR ===
echo Noticia do video: %ULTIMO%
echo Sera criado um video NOVO (roteiro, voz e edicao) com o texto completo da materia,
echo publicado no Instagram e enviado como rascunho ao TikTok.
echo.
set /p RESP=Continuar? (S/N):
if /i not "%RESP%"=="S" ( echo Nada foi feito. & pause & exit /b 0 )
".venv\Scripts\python.exe" main.py --refazer-noticia "saida\%ULTIMO%"
echo.
pause

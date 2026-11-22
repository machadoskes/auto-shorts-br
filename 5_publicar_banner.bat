@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Publicar banner do perfil
echo === Publicar o banner (3 imagens) no seu perfil ===
echo Ordem: direita, meio, esquerda (perfil\banner_final\api_4x5_*.jpg)
echo Pause o agendamento antes (desagendar.bat) para nenhum Reels entrar no meio.
echo.
set /p RESP=Publicar as 3 imagens agora? (S/N): 
if /i not "%RESP%"=="S" ( echo Nada foi publicado. & pause & exit /b 0 )
".venv\Scripts\python.exe" main.py --publicar-banner
echo.
pause

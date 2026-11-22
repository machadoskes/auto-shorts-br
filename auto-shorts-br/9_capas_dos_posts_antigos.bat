@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Gerar capas padronizadas para os Reels antigos
".venv\Scripts\python.exe" main.py --capas-antigas
echo.
echo As capas estao em perfil\capas_antigas (nome = data + titulo do post).
explorer "perfil\capas_antigas"
pause

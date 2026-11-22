@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Conectar TikTok
echo === Conectar a conta do TikTok (uma vez) ===
echo O navegador vai abrir a tela do TikTok: entre na sua conta e autorize.
echo.
".venv\Scripts\python.exe" main.py --conectar-tiktok
echo.
pause

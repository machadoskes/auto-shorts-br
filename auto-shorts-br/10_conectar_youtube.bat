@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Conectar YouTube
echo === Conectar o canal do YouTube (uma vez) ===
echo O navegador vai abrir o login do Google: escolha a conta do seu canal.
echo Se aparecer "O Google nao verificou este app", clique em Continuar (o app e seu).
echo Marque a permissao de enviar videos e confirme.
echo.
".venv\Scripts\python.exe" main.py --conectar-youtube
echo.
pause

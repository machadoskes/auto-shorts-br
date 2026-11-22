@echo off
chcp 65001 >nul
title Pausar publicacoes automaticas
schtasks /delete /tn "Auto Shorts" /f
echo Publicacoes automaticas pausadas. Para voltar, rode agendar.bat.
pause

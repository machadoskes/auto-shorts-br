@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
set SAIDA=logs\verificacao.txt
echo === Verificacao %date% %time% === > %SAIDA%

echo [python base] >> %SAIDA%
where python >> %SAIDA% 2>&1
where py >> %SAIDA% 2>&1

echo [ambiente isolado .venv] >> %SAIDA%
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >> %SAIDA% 2>&1
  ".venv\Scripts\python.exe" -c "import requests, feedparser, dotenv, PIL, edge_tts; print('BIBLIOTECAS_OK')" >> %SAIDA% 2>&1
) else (
  echo .venv NAO EXISTE >> %SAIDA%
)

echo [ffmpeg local] >> %SAIDA%
if exist "ffmpeg\ffmpeg.exe" (
  "ffmpeg\ffmpeg.exe" -version 2>&1 | findstr /b "ffmpeg version" >> %SAIDA%
) else (
  echo ffmpeg\ffmpeg.exe NAO EXISTE >> %SAIDA%
)

echo [env] >> %SAIDA%
if exist ".env" (echo .env EXISTE >> %SAIDA%) else (echo .env NAO EXISTE >> %SAIDA%)
findstr /r /c:"^GEMINI_API_KEY=..*" .env >nul 2>&1 && echo GEMINI_API_KEY PREENCHIDA >> %SAIDA%

echo Verificacao concluida. Resultado em %SAIDA%
pause

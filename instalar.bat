@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Instalacao ISOLADA: tudo fica dentro desta pasta ===
echo.

rem --- 1. Python base (usado apenas para criar o ambiente isolado) ---
set PYBASE=python
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://www.python.org/downloads/
    pause & exit /b 1
  )
  set PYBASE=py
)

rem --- 2. Ambiente virtual em .venv (bibliotecas ficam so aqui) ---
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente isolado em .venv ...
  %PYBASE% -m venv .venv
  if errorlevel 1 ( echo [ERRO] Falha ao criar o .venv & pause & exit /b 1 )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERRO] Falha ao instalar bibliotecas & pause & exit /b 1 )

rem --- 3. ffmpeg portatil em .\ffmpeg (sem instalar no Windows) ---
if not exist "ffmpeg\ffmpeg.exe" (
  echo Baixando ffmpeg portatil ^(cerca de 100 MB^)...
  if not exist ffmpeg mkdir ffmpeg
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$zip=Join-Path $PWD 'ffmpeg\ffmpeg.zip';" ^
    "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip;" ^
    "Expand-Archive -Path $zip -DestinationPath 'ffmpeg\tmp' -Force;" ^
    "Get-ChildItem 'ffmpeg\tmp' -Recurse -Include ffmpeg.exe,ffprobe.exe | Copy-Item -Destination 'ffmpeg';" ^
    "Remove-Item $zip; Remove-Item 'ffmpeg\tmp' -Recurse -Force"
  if not exist "ffmpeg\ffmpeg.exe" (
    echo [ERRO] Nao foi possivel baixar o ffmpeg. Avise o Claude.
    pause & exit /b 1
  )
)

rem --- 4. Configuracao do canal e arquivo de chaves secretas ---
if not exist "config.json" (
  copy "config-exemplo.json" "config.json" >nul
  echo Arquivo config.json criado. Abra-o e preencha a secao "canal" e as "fontes_rss".
)
if not exist ".env" (
  copy "env-exemplo.txt" ".env" >nul
  echo Arquivo .env criado. Abra-o e cole sua GEMINI_API_KEY.
)

for %%p in (midia\videos midia\imagens midia\trailers midia\musicas midia\externas) do if not exist "%%p" mkdir "%%p"

echo.
echo === Instalacao concluida ===
echo Teste com:  rodar.bat --teste
pause

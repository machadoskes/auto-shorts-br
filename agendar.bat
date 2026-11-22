@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agendar publicacoes automaticas
echo === Agendamento automatico: 4 posts por dia ===
echo  09:40, 12:40, 17:40 e 20:40 (no ar por volta de 10h, 13h, 18h e 21h)
echo  Para mudar os horarios, edite a linha com os horarios neste arquivo.
echo - Se o computador estiver suspenso, ele acorda para rodar.
echo - Se estiver desligado, roda assim que ligar (intervalo minimo de 2h30 entre posts).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$acao = New-ScheduledTaskAction -Execute '%~dp0rodar.bat' -WorkingDirectory '%~dp0';" ^
  "$gatilhos = @('09:40','12:40','17:40','20:40') | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ };" ^
  "$conf = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew;" ^
  "Register-ScheduledTask -TaskName 'Auto Shorts' -Action $acao -Trigger $gatilhos -Settings $conf -Description 'Gera e publica videos curtos automaticamente' -Force | Out-Null;" ^
  "Get-ScheduledTask -TaskName 'Auto Shorts' | Select-Object TaskName, State | Format-Table -AutoSize"

if errorlevel 1 (
  echo [ERRO] Nao foi possivel criar a tarefa. Avise o Claude.
) else (
  echo Tarefa "Auto Shorts" atualizada. Para pausar, rode desagendar.bat.
)
pause

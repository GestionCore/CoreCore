# Horas objetivo
$horaEnter = (Get-Date).Date.AddHours(19).AddMinutes(1)
$horaApagado = (Get-Date).Date.AddHours(19).AddMinutes(17)
$ahora = Get-Date

# 1. Espera y pulsación de ENTER a las 19:01
if ($ahora -lt $horaEnter) {
    $segundosHastaEnter = ($horaEnter - $ahora).TotalSeconds
    Write-Host "Esperando $($segundosHastaEnter -as [int]) segundos hasta las 19:01 para apretar Enter..."
    Start-Sleep -Seconds $segundosHastaEnter

    $wshell = New-Object -ComObject wscript.shell
    $wshell.SendKeys('{ENTER}')
    Write-Host "¡Enter presionado a las 19:01!"
} else {
    Write-Host "La hora de Enter (19:01) ya pasó. Continuando con la programación del apagado..."
}

# 2. Espera hasta las 19:17 y apagado del sistema
$ahora = Get-Date
if ($ahora -lt $horaApagado) {
    $segundosHastaApagado = ($horaApagado - $ahora).TotalSeconds
    Write-Host "Esperando $($segundosHastaApagado -as [int]) segundos hasta las 19:17 para apagar la PC..."
    Start-Sleep -Seconds $segundosHastaApagado

    Write-Host "Apagando el equipo..."
    # Fuerza el cierre de aplicaciones y apaga de inmediato
    shutdown /s /f /t 0
} else {
    Write-Host "La hora de apagado ya pasó."
}
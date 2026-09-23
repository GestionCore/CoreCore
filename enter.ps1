# Horas objetivo para hoy a la mañana
$horaEnter = (Get-Date).Date.AddHours(7).AddMinutes(13)
$ahora = Get-Date

# 1. Espera y pulsación de ENTER a las 07:13 AM
if ($ahora -lt $horaEnter) {
    $segundosHastaEnter = ($horaEnter - $ahora).TotalSeconds
    Write-Host "Esperando $($segundosHastaEnter -as [int]) segundos hasta las 07:13 AM para apretar Enter..."
    Start-Sleep -Seconds $segundosHastaEnter

    $wshell = New-Object -ComObject wscript.shell
    $wshell.SendKeys('{ENTER}')
    Write-Host "¡Enter presionado a las 07:13 AM!"
} else {
    Write-Host "La hora de Enter (07:13 AM) ya pasó."
}
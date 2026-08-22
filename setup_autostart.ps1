# Evy Auto-Start Setup Script
# Auto-elevate to admin if not already running as admin

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$taskName = "EvyAssistantAutoStart"
$vbsPath = "C:\Users\NOTRON.SAN\Documents\Proyek Portofolio\AI SPEECH\start_evy_minimized.vbs"

Write-Host "=== Evy Auto-Start Setup ===" -ForegroundColor Cyan
Write-Host ""

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Menghapus task lama: $taskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""

$trigger = New-ScheduledTaskTrigger -AtLogon
$trigger.Delay = "PT5M"

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal

Write-Host ""
Write-Host "Task '$taskName' berhasil didaftarkan!" -ForegroundColor Green
Write-Host ""
Write-Host "Evy akan otomatis jalan 5 menit setelah kamu login, di background, dengan admin rights." -ForegroundColor White
Write-Host ""
Write-Host "Untuk menghapus auto-start, jalankan PowerShell admin:" -ForegroundColor Yellow
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:false" -ForegroundColor Gray
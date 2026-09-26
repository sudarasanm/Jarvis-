# Stop Jarvis starting when you log in (and stop the running copy).
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1

$root = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Jarvis.lnk"
if (Test-Path $lnk) {
    Remove-Item $lnk
    Write-Host "Jarvis will no longer start when you log in." -ForegroundColor Green
} else {
    Write-Host "Autostart wasn't set up."
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $python) { & $python -m jarvis --stop }

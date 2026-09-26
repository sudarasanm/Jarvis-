# Start Jarvis automatically when you log in: silently, in the background, restarted if it crashes.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
#
# Puts a shortcut in your Startup folder that runs `pythonw -m jarvis --service` (no console window).
# Runs as you: no administrator rights needed or used. Undo with scripts\uninstall_autostart.ps1.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Host "Couldn't find $pythonw. Run install.ps1 first." -ForegroundColor Red
    exit 1
}

function New-Shortcut($path, $arguments, $description) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $root
    $lnk.Description = $description
    $lnk.Save()
}

$startup = [Environment]::GetFolderPath("Startup")
New-Shortcut (Join-Path $startup "Jarvis.lnk") "-m jarvis --service" "Jarvis voice assistant (background)"
Write-Host "Jarvis will start automatically when you log in." -ForegroundColor Green

if ($args -notcontains "-NoStart") {
    & (Join-Path $root ".venv\Scripts\python.exe") -m jarvis --stop | Out-Null
    Start-Process -FilePath $pythonw -ArgumentList "-m", "jarvis", "--service" -WorkingDirectory $root
    Write-Host "Jarvis is running in the background now. Look for the glowing circle in the tray."
}

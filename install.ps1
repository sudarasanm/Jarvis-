# One-time Jarvis setup for Windows.
#
# Run from the Jarvis folder:
#     powershell -ExecutionPolicy Bypass -File install.ps1
#
# It installs everything, asks for your Anthropic API key, makes Jarvis start
# automatically (silently, in the background) when you log in, adds desktop
# shortcuts, and starts Jarvis right away. Safe to run again to update.

# Not "Stop": Windows PowerShell 5.1 would turn harmless pip warnings into fatal errors.
# Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- 1. Python 3.10 to 3.13 (PyAudio, the microphone library, has no Windows package for 3.14 yet) ---
function Find-Python {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $null }
    foreach ($v in "3.13", "3.12", "3.11", "3.10") {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Say "Installing Python 3.13 (your Python 3.14 stays as it is)..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Please install Python 3.13 from https://www.python.org/downloads/ and run this installer again."
    }
    winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
    $python = Find-Python
    if (-not $python) {
        $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
        if (Test-Path $candidate) { $python = $candidate }
    }
    if (-not $python) { throw "Couldn't find Python 3.13 after installing it. Close this window, open a new one and run the installer again." }
}
Say "Using Python: $python"

# --- 2. Virtual environment + packages ---
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (Test-Path $venvPython) {
    & $venvPython -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Say "Replacing the old .venv (it was built with an unsupported Python)..."
        Remove-Item -Recurse -Force (Join-Path $root ".venv")
    }
}
if (-not (Test-Path $venvPython)) {
    Say "Creating the virtual environment..."
    & $python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create the virtual environment." }
}
Say "Installing packages (this can take a minute)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $root "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Package installation failed. Scroll up for the error." }

# --- 3. Settings (saved in %USERPROFILE%\.jarvis.json, outside the code folder) ---
$hasKey = & $venvPython -c "import os; from jarvis.config import load_settings; print(bool(os.environ.get('ANTHROPIC_API_KEY') or load_settings().get('anthropic_api_key')))"
if ("$hasKey".Trim() -ne "True") {
    Write-Host ""
    Write-Host "Jarvis uses Claude to talk with you. Paste your Anthropic API key (starts with sk-ant-)."
    Write-Host "Get one at https://platform.claude.com -> API Keys. Press Enter to skip for now."
    $secure = Read-Host "API key" -AsSecureString
    $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if ($key) {
        $env:JARVIS_SETUP_VALUE = $key.Trim()
        & $venvPython -c "import os; from jarvis.config import save_setting; save_setting('anthropic_api_key', os.environ['JARVIS_SETUP_VALUE'])"
        Remove-Item Env:\JARVIS_SETUP_VALUE
        Say "API key saved."
    }
}

$hasLang = & $venvPython -c "from jarvis.config import load_settings; print('language' in load_settings())"
if ("$hasLang".Trim() -ne "True") {
    Write-Host ""
    Write-Host "Which English should Jarvis listen for? Matching your accent makes it understand you much better."
    Write-Host "  1) Indian English (en-IN)   2) US English (en-US)   3) British English (en-GB)"
    $choice = Read-Host "Choose 1, 2 or 3 (Enter = 1)"
    $lang = "en-IN"
    if ($choice -eq "2") { $lang = "en-US" }
    if ($choice -eq "3") { $lang = "en-GB" }
    $env:JARVIS_SETUP_VALUE = $lang
    & $venvPython -c "import os; from jarvis.config import save_setting; save_setting('language', os.environ['JARVIS_SETUP_VALUE'])"
    Remove-Item Env:\JARVIS_SETUP_VALUE
}

# --- 4. Shortcuts: start at login, plus Start / Stop on the desktop ---
function New-Shortcut($path, $arguments, $description) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $venvPythonw
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $root
    $lnk.Description = $description
    $lnk.Save()
}
$startup = [Environment]::GetFolderPath("Startup")
$desktop = [Environment]::GetFolderPath("Desktop")
New-Shortcut (Join-Path $startup "Jarvis.lnk") "-m jarvis" "Start Jarvis in the background"
New-Shortcut (Join-Path $desktop "Jarvis.lnk") "-m jarvis" "Start Jarvis in the background"
New-Shortcut (Join-Path $desktop "Stop Jarvis.lnk") "-m jarvis --stop" "Stop Jarvis"
Say "Jarvis will now start automatically when you log in."

# --- 5. Start it now (restarting any copy that's already running) ---
& $venvPython -m jarvis --stop | Out-Null
Start-Process -FilePath $venvPythonw -ArgumentList "-m", "jarvis" -WorkingDirectory $root
Write-Host ""
Say "Jarvis is running in the background. Say 'Jarvis' to start a conversation."
Write-Host "    Stop it:   double-click 'Stop Jarvis' on the desktop, or say 'Jarvis, go offline'"
Write-Host "    Log file:  $env:USERPROFILE\.jarvis.log"

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
function Save-Setting($key, $value) {
    $env:JARVIS_SETUP_KEY = $key
    $env:JARVIS_SETUP_VALUE = $value
    & $venvPython -c "import os; from jarvis.config import save_setting; save_setting(os.environ['JARVIS_SETUP_KEY'], os.environ['JARVIS_SETUP_VALUE'])"
    Remove-Item Env:\JARVIS_SETUP_KEY
    Remove-Item Env:\JARVIS_SETUP_VALUE
}

function Read-Secret($prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    return "$plain".Trim()
}

# Brains: Google Gemini (free, main) + Ollama (free, offline backup). Claude is optional and paid.
$hasGemini = & $venvPython -c "import os; from jarvis.config import load_settings; print(bool(os.environ.get('GEMINI_API_KEY') or load_settings().get('gemini_api_key')))"
if ("$hasGemini".Trim() -ne "True") {
    Write-Host ""
    Write-Host "Jarvis's main brain is Google Gemini, which is FREE (no card needed)."
    Write-Host "Your browser will open https://aistudio.google.com/apikey : sign in with Google, click"
    Write-Host "'Create API key', copy it and paste it here. Press Enter to skip."
    Start-Process "https://aistudio.google.com/apikey"
    $key = Read-Secret "Gemini API key"
    if ($key) { Save-Setting "gemini_api_key" $key; Say "Gemini key saved." }
}
Save-Setting "ai_provider" "gemini"

$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollama)) {
    $found = Get-Command ollama -ErrorAction SilentlyContinue
    if ($found) { $ollama = $found.Source }
}
$skipOllama = & $venvPython -c "from jarvis.config import load_settings; print(load_settings().get('ollama_setup') == 'skip')"
if (-not (Test-Path $ollama) -and "$skipOllama".Trim() -ne "True") {
    Write-Host ""
    Write-Host "Ollama is a FREE backup brain that runs on this PC, so Jarvis keeps talking when Gemini's"
    Write-Host "free limit runs out or the internet is down. It needs about 2 GB of disk and 8 GB+ of RAM."
    $answer = Read-Host "Install Ollama now? (Y/n)"
    if ($answer -eq "" -or $answer -match "^[yY]") {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Say "Installing Ollama..."
            winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        } else {
            Write-Host "Please install Ollama from https://ollama.com/download and run this installer again."
        }
    } else {
        Save-Setting "ollama_setup" "skip"
    }
}
if (Test-Path $ollama) {
    $model = & $venvPython -c "from jarvis.config import Config; print(Config().ollama_model)"
    $model = "$model".Trim()
    & $ollama list 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
    $have = (& $ollama list 2>$null | Out-String)
    if ($have -notmatch [regex]::Escape($model)) {
        Say "Downloading the $model model for Ollama (about 2 GB, one time)..."
        & $ollama pull $model
    }
    Say "Ollama backup brain is ready."
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
    Save-Setting "language" $lang
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
# The service restarts Jarvis if it ever crashes. Runs as you, never as administrator.
New-Shortcut (Join-Path $startup "Jarvis.lnk") "-m jarvis --service" "Start Jarvis in the background"
New-Shortcut (Join-Path $desktop "Jarvis.lnk") "-m jarvis --service" "Start Jarvis in the background"
New-Shortcut (Join-Path $desktop "Stop Jarvis.lnk") "-m jarvis --stop" "Stop Jarvis"
Say "Jarvis will now start automatically when you log in."

# --- 5. Start it now (restarting any copy that's already running) ---
& $venvPython -m jarvis --stop | Out-Null
Start-Process -FilePath $venvPythonw -ArgumentList "-m", "jarvis", "--service" -WorkingDirectory $root
Write-Host ""
Say "Jarvis is running in the background. Say 'Hey Jarvis', or press Ctrl+Alt+J."
Write-Host "    Stop it:   the tray circle's Exit, double-click 'Stop Jarvis' on the desktop, or say 'Jarvis, go offline'"
Write-Host "    Log file:  $root\logs\jarvis.log   (watch live: .venv\Scripts\python -m jarvis --logs)"

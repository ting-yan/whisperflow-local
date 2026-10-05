# WhisperFlow Local - one-time setup.
# Installs Python 3.12 if missing, asks which languages you speak and
# whether to use an NVIDIA GPU, installs dependencies, creates desktop +
# startup shortcuts, and launches the app. Re-run it any time to change
# those two answers; other settings in config.json are kept.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# --- Find a real Python (ignore the Microsoft Store stub) -------------------
function Find-Python {
    $fixed = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (Test-Path $fixed) { return $fixed }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { return $cmd.Source }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Installing Python 3.12 (one-time)..." -ForegroundColor Cyan
    winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
    $py = Find-Python
    if (-not $py) { throw "Python install failed - install Python 3.12 manually from python.org, then re-run setup.bat" }
}
Write-Host "Using Python: $py"
$configure = Join-Path $root "scripts\configure.py"

# --- Languages ---------------------------------------------------------------
# Auto-detect only chooses between the languages picked here, so pick only
# the ones you actually speak - each extra one is another way to guess wrong.
# configure.py is stdlib-only, so this works before dependencies install.
Write-Host ""
Write-Host "Which languages will you dictate in?" -ForegroundColor Cyan
& $py $configure --list
$current = (& $py $configure --current).Trim()
while ($true) {
    $answer = Read-Host "Numbers or codes, comma-separated (Enter = $current)"
    if (-not $answer.Trim()) { $answer = $current }
    & $py $configure --languages $answer
    if ($LASTEXITCODE -eq 0) { break }
}

# --- GPU or CPU --------------------------------------------------------------
# The speech engine (CTranslate2) can only use NVIDIA GPUs. AMD Radeon and
# Intel graphics aren't supported, so those machines always run on the CPU,
# which works fine on Intel and AMD Ryzen processors alike.
$useGpu = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpuName = (& nvidia-smi --query-gpu=name --format=csv,noheader | Select-Object -First 1)
    Write-Host ""
    Write-Host "NVIDIA GPU found: $gpuName" -ForegroundColor Cyan
    Write-Host "  GPU: ~5x faster dictation; downloads NVIDIA's CUDA runtime (~700 MB, one-time)."
    Write-Host "  CPU: no extra download; slower, especially with the bigger models."
    $answer = Read-Host "Use the GPU? [Y/n]"
    $useGpu = $answer.Trim() -notmatch '^(n|no)$'
} else {
    Write-Host ""
    Write-Host "No NVIDIA GPU found - WhisperFlow will run on the CPU." -ForegroundColor Cyan
}

# --- Dependencies ------------------------------------------------------------
Write-Host ""
Write-Host "Installing dependencies (this can take a minute)..." -ForegroundColor Cyan
& $py -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$device = "cpu"
if ($useGpu) {
    Write-Host "Installing NVIDIA CUDA runtime (~700 MB, one-time)..." -ForegroundColor Cyan
    & $py -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9" --quiet --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) {
        # "auto" rather than "cuda": GPU when it works, and if a driver update
        # ever breaks it the app falls back to the CPU instead of not starting.
        $device = "auto"
    } else {
        Write-Host "CUDA runtime install failed - the app will run on the CPU." -ForegroundColor Yellow
    }
}
& $py $configure --device $device
if ($LASTEXITCODE -ne 0) { throw "could not write config.json" }

# --- Shortcuts -----------------------------------------------------------
# Best-effort: some machines block .lnk writes to Desktop (Controlled Folder
# Access, antivirus). That should not stop setup - deps are already
# installed at this point, so fall through to launching the app either way.
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
$app = Join-Path $root "app.py"
try {
    $ws = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Startup'))) {
        $sc = $ws.CreateShortcut("$dir\WhisperFlow Local.lnk")
        $sc.TargetPath = $pyw
        $sc.Arguments = "`"$app`""
        $sc.WorkingDirectory = $root
        $sc.IconLocation = "$root\icon.ico"
        $sc.Description = "Local push-to-talk dictation"
        $sc.Save()
    }
    Write-Host "Shortcuts created (Desktop + Startup)." -ForegroundColor Green
} catch {
    Write-Host "Could not create shortcuts (often Controlled Folder Access or antivirus blocking Desktop writes)." -ForegroundColor Yellow
    Write-Host "The app still works - launch it with run.bat. For auto-start, manually copy a shortcut into:" -ForegroundColor Yellow
    Write-Host "  $([Environment]::GetFolderPath('Startup'))" -ForegroundColor Yellow
}

# --- Launch ------------------------------------------------------------------
Write-Host "Launching WhisperFlow Local - first run downloads the speech model (~75 MB)." -ForegroundColor Green
Start-Process $pyw -ArgumentList "`"$app`"" -WorkingDirectory $root
Write-Host "Done! Hold F8 in any app to dictate. Settings live in the tray icon."

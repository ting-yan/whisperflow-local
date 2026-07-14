# WhisperFlow Local - one-time setup.
# Installs Python 3.12 if missing, installs dependencies, creates
# desktop + startup shortcuts, and launches the app.

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

# --- Dependencies ------------------------------------------------------------
Write-Host "Installing dependencies (this can take a minute)..." -ForegroundColor Cyan
& $py -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

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

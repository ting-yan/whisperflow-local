# WhisperFlow Local - update a source install in place.
# Run by the app's "Update available" link (or update.bat by hand):
# waits for the app to close, downloads the latest release's source, copies
# it over this folder, re-installs dependencies, and restarts the app.
#
# config.json isn't in the download, so settings are kept. A git checkout is
# updated with "git pull" instead, so it doesn't end up full of changes.

param(
    [int]$WaitPid = 0,     # app process to wait for before touching files
    [string]$Tag = "",     # release tag to install; default = latest
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$repo = "ting-yan/whisperflow-local"

function Find-Python {
    $fixed = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (Test-Path $fixed) { return $fixed }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { return $cmd.Source }
    return $null
}

try {
    if ($WaitPid) {
        Write-Host "Waiting for WhisperFlow Local to close..."
        Wait-Process -Id $WaitPid -Timeout 30 -ErrorAction SilentlyContinue
    }

    $py = Find-Python
    if (-not $py) { throw "Python not found - run setup.bat instead" }

    if (Test-Path (Join-Path $root ".git")) {
        Write-Host "Git checkout - pulling..." -ForegroundColor Cyan
        & git -C $root pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw "git pull failed - resolve it in $root, then re-run" }
    } else {
        # PowerShell 5.1 defaults to TLS 1.0, which GitHub refuses.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        if (-not $Tag) {
            $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -UseBasicParsing
            $Tag = $release.tag_name
        }
        Write-Host "Downloading WhisperFlow Local $Tag..." -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "whisperflow-update-$PID"
        New-Item -ItemType Directory -Force $tmp | Out-Null
        $zip = Join-Path $tmp "src.zip"
        Invoke-WebRequest "https://github.com/$repo/archive/refs/tags/$Tag.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath $tmp -Force
        # GitHub wraps the source in one folder, e.g. whisperflow-local-1.4.0
        $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
        Copy-Item (Join-Path $src.FullName "*") $root -Recurse -Force
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Updating dependencies..." -ForegroundColor Cyan
    & $py -m pip install -r requirements.txt --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    Write-Host "Updated." -ForegroundColor Green
    if (-not $NoRestart) {
        $pyw = Join-Path (Split-Path $py) "pythonw.exe"
        Start-Process $pyw -ArgumentList "`"$(Join-Path $root 'app.py')`"" -WorkingDirectory $root
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Host ""
    Write-Host "Update failed: $_" -ForegroundColor Red
    Write-Host "Your settings (config.json) are untouched. Re-run update.bat, or download the"
    Write-Host "source again from https://github.com/$repo and run setup.bat."
    Read-Host "Press Enter to close"
    exit 1
}

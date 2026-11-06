# Keeps the Navrist backend (port 8000) and web app (port 3100) running.
# Every 10 seconds it checks both ports and starts whichever one is down, so a crash or a closed tool never leaves
# localhost dead. Output goes to data\dev-logs. Run it once (start_navrist.bat does this); it survives closing the editor.
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\dev-logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Test-Port([int]$port) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $c.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $c.Close() }
}

function Start-Hidden([string]$file, [string]$arguments, [string]$dir, [string]$name) {
  Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $dir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs "$name.log") -RedirectStandardError (Join-Path $logs "$name.err.log") | Out-Null
}

$last = @{ api = [datetime]::MinValue; web = [datetime]::MinValue }
while ($true) {
  if (-not (Test-Port 8000) -and ((Get-Date) - $last.api).TotalSeconds -gt 60) {
    Start-Hidden (Join-Path $root "venv\Scripts\python.exe") "app.py" $root "api"
    $last.api = Get-Date
  }
  if (-not (Test-Port 3100) -and ((Get-Date) - $last.web).TotalSeconds -gt 60) {
    # Serves the PRODUCTION build (folder .next-prod, made by scripts\build_web.ps1). If no build exists yet, fall back to the
    # dev server so localhost is never dead. Rebuild with scripts\build_web.ps1 after changing the web code.
    $web = Join-Path $root "navrist-web"
    if (Test-Path (Join-Path $web ".next-prod\BUILD_ID")) {
      Start-Hidden "cmd.exe" "/c set NEXT_DIST_DIR=.next-prod&& npm run start -- -p 3100" $web "web"
    } else {
      Start-Hidden "cmd.exe" "/c npm run dev -- -p 3100" $web "web"
    }
    $last.web = Get-Date
  }
  Start-Sleep -Seconds 10
}

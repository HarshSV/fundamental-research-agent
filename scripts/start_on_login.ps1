# Runs at Windows login (from a shortcut in the user's Startup folder): starts the Navrist keeper (which runs the backend on port 8000 and
# the web app on port 3100) and the Cloudflare tunnel for ai.navrist.com, each only if it is not already running. Safe to run again.
# Log: data\dev-logs\startup.log
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\dev-logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
function Log([string]$m) { Add-Content -Path (Join-Path $logs "startup.log") -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) }

Log "login start"
Start-Sleep -Seconds 20          # let the network and the desktop come up first

$keeper = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*keep_running.ps1*' }
if (-not $keeper) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'scripts\keep_running.ps1')
  Log "keeper started"
} else { Log "keeper already running" }

$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
  $exe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
  if (Test-Path $exe) {
    Start-Process -FilePath $exe -ArgumentList 'tunnel', 'run', 'navrist' -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $logs "tunnel.log") -RedirectStandardError (Join-Path $logs "tunnel.err.log")
    Log "tunnel started"
  } else { Log "cloudflared not found at $exe" }
} else { Log "tunnel already running" }

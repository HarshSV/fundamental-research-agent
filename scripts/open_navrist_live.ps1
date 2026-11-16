# Desktop icon "Navrist AI (ai.navrist.com)": makes sure the backend, web app and Cloudflare tunnel are running (starting whichever is not),
# waits until the live site answers, then opens https://ai.navrist.com in the default browser. Safe to run any time.
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\dev-logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$keeper = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*keep_running.ps1*' -and $_.ProcessId -ne $PID }
if (-not $keeper) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'scripts\keep_running.ps1')
  Write-Host "Starting Navrist in the background..."
}
if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
  $exe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
  if (Test-Path $exe) {
    Start-Process -FilePath $exe -ArgumentList 'tunnel', 'run', 'navrist' -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $logs "tunnel.log") -RedirectStandardError (Join-Path $logs "tunnel.err.log")
    Write-Host "Starting the tunnel..."
  }
}

function Test-Up([string]$url) { try { (Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 8).StatusCode -eq 200 } catch { $false } }
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
  if ((Test-Up 'http://localhost:3100') -and (Test-Up 'https://ai.navrist.com')) { break }
  Start-Sleep -Seconds 3
}
if (Test-Up 'https://ai.navrist.com') {
  Start-Process 'https://ai.navrist.com'
  Write-Host "Opened https://ai.navrist.com"
} elseif (Test-Up 'http://localhost:3100') {
  Start-Process 'http://localhost:3100'
  Write-Host "The live site is not answering yet (tunnel); opened http://localhost:3100 instead."
} else {
  Write-Host "The app is not answering yet. Look at data\dev-logs for the reason."
  Start-Sleep -Seconds 10
}

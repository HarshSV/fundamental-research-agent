# Starts the keeper (once), waits for the app to answer, then opens it in the default browser.
$root = Split-Path -Parent $PSScriptRoot
$running = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*keep_running.ps1*' -and $_.ProcessId -ne $PID }
if (-not $running) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'scripts\keep_running.ps1')
  Write-Host "Starting Navrist in the background..."
} else {
  Write-Host "Navrist is already being kept running."
}

function Test-Up([string]$url) { try { (Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5).StatusCode -eq 200 } catch { $false } }
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
  if ((Test-Up 'http://localhost:3100') -and (Test-Up 'http://127.0.0.1:8000/docs')) { break }
  Start-Sleep -Seconds 3
}
if ((Test-Up 'http://localhost:3100')) {
  Start-Process 'http://localhost:3100'
  Write-Host "Opened http://localhost:3100"
} else {
  Write-Host "The app is not answering yet. Look at data\dev-logs for the reason."
}

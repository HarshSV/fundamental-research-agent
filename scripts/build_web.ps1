# Rebuilds the production web app (navrist-web -> .next-prod) and restarts it, so ai.navrist.com and localhost:3100 show the
# latest code. The keeper (scripts\keep_running.ps1) starts the new server within about a minute of the old one stopping.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build_web.ps1
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "navrist-web"
Push-Location $web
try {
  $env:NEXT_DIST_DIR = ".next-prod"
  npm run build
  if ($LASTEXITCODE -ne 0) { Write-Host "Build failed - the running site was not touched."; exit 1 }
} finally { Pop-Location }

# stop whatever serves port 3100 (matched by its command line: the listener's owner id is not always readable); the keeper brings the new build up
$old = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @("node.exe", "cmd.exe") -and $_.CommandLine -match "(npm|next).*(start).*-p 3100" }
foreach ($p in $old) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Build done. The site restarts within about a minute."

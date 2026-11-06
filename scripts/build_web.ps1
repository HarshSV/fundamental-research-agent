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

# stop whatever serves port 3100; the keeper brings the new build up
$conn = Get-NetTCPConnection -LocalPort 3100 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn -and $conn.OwningProcess -gt 0) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Write-Host "Build done. The site restarts within about a minute."

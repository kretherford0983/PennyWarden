# v1.5.0 CR-026: smoke test of a Windows build - start it with an empty data folder, check /api/health and the
# version reported by /api/system/status, then stop it (with its child processes). 2.1.1: first, that slide decks
# and Word files can be made.
#   pwsh packaging/windows/smoke_test.ps1 -Command <path to .exe or .cmd> -Version 1.5.0 -Port 8791
param(
  [Parameter(Mandatory = $true)][string]$Command,
  [Parameter(Mandatory = $true)][string]$Version,
  [int]$Port = 8791,
  [int]$TimeoutSeconds = 120
)
$ErrorActionPreference = "Stop"
$data = Join-Path ([System.IO.Path]::GetTempPath()) ("fm-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $data | Out-Null
$log = "$data.log"
# 2.1.1: slide decks and Word files can be made with the bundled python-pptx / python-docx templates (they broke in
# the macOS app; Windows resolves "..\" in their template paths by text, so it is checked here too)
& $Command self-check-documents
if ($LASTEXITCODE -ne 0) { Write-Host "::error::smoke test failed for ${Command}: slide decks or Word files can't be made"; exit 1 }
$args_ = @("--no-browser", "--port", "$Port", "--data-dir", "`"$data`"")
Write-Host "Starting $Command (data: $data)"
$p = Start-Process -FilePath $Command -ArgumentList $args_ -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
try {
  $ok = $false
  for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    if ($p.HasExited) { throw "the program exited early with code $($p.ExitCode)" }
    try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2; if ($h.status -eq "ok") { $ok = $true; break } } catch { }
    Start-Sleep -Seconds 1
  }
  if (-not $ok) { throw "no healthy answer on port $Port within $TimeoutSeconds s" }
  Write-Host "healthy after $i s"
  $s = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/system/status"
  $s | ConvertTo-Json -Compress | Write-Host
  if ($s.version -ne $Version) { throw "reports version '$($s.version)', expected '$Version'" }
  if ($s.mode -ne "local") { throw "expected local mode by default, got '$($s.mode)'" }
  $page = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing
  if ($page.Content -notmatch "<div id=`"root`">") { throw "the web interface is missing" }
  $lic = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/system/legal/license" -UseBasicParsing
  if ($lic.Content -notmatch "GNU AFFERO GENERAL PUBLIC LICENSE") { throw "LICENSE is not bundled" }
  if (-not (Test-Path (Join-Path $data "database"))) { throw "the data folder was not used" }
  Write-Host "SMOKE TEST PASSED: $Command"
} catch {
  Write-Host "::error::smoke test failed for ${Command}: $_"
  if (Test-Path $log) { Get-Content $log -Tail 40 }
  if (Test-Path "$log.err") { Get-Content "$log.err" -Tail 40 }
  exit 1
} finally {
  & taskkill /T /F /PID $p.Id 2>$null | Out-Null
}

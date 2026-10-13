# 2.0.0 (#187): tests install-windows-server.ps1 on the Windows build runner (Windows Server): a new installation, an
# upgrade that keeps the data, and an uninstall that keeps the data. Caddy is not tested here (it needs a real domain).
#   pwsh packaging/windows/test_server_installer.ps1 -Zip release/PennyWarden-windows-x64.zip -Nssm dist/nssm.exe -Version 2.0.0
param(
  [Parameter(Mandatory = $true)][string]$Zip,
  [Parameter(Mandatory = $true)][string]$Nssm,
  [Parameter(Mandatory = $true)][string]$Version,
  [int]$Port = 8795
)
$ErrorActionPreference = "Stop"
$installer = Join-Path $PSScriptRoot "install-windows-server.ps1"
$inst = "C:\pw-ci"
$data = "C:\ProgramData\PennyWarden-ci"
$zipFull = (Resolve-Path $Zip).Path
$nssmFull = (Resolve-Path $Nssm).Path

function Check([bool]$ok, [string]$what) {
  if (-not $ok) { Write-Host "::error::server installer test failed: $what"; throw $what }
  Write-Host "ok - $what"
}

function Run-Installer([string[]]$more) {
  # Windows PowerShell 5.1, as an Administrator would run it on a server
  $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $installer, "-Yes", "-InstallDir", $inst, "-DataDir", $data) + $more
  & powershell.exe @a
  return $LASTEXITCODE
}

function Get-Acct { (Get-CimInstance Win32_Service -Filter "Name='PennyWarden'").StartName }

try {
  # ---- new installation
  $rc = Run-Installer @("-Version", "v$Version", "-ZipPath", $zipFull, "-NssmPath", $nssmFull, "-Port", "$Port")
  Check ($rc -eq 0) "new installation exits with 0 (got $rc)"
  $svc = Get-Service PennyWarden
  Check ($svc.Status -eq "Running") "the PennyWarden service is running"
  Check ((Get-Acct) -eq "NT SERVICE\PennyWarden") "it runs as NT SERVICE\PennyWarden (got '$(Get-Acct)')"
  Check ((Get-CimInstance Win32_Service -Filter "Name='PennyWarden'").StartMode -eq "Auto") "it starts with Windows"
  $st = Invoke-RestMethod "http://127.0.0.1:$Port/api/system/status"
  Check ($st.mode -eq "server" -and $st.version -eq $Version) "it answers in server mode with version $Version"
  Check (Test-Path "$data\config.toml") "config.toml was written"
  $cfg = Get-Content "$data\config.toml" -Raw
  Check ($cfg -match 'host = "127.0.0.1"' -and $cfg -match "port = $Port") "config.toml binds to 127.0.0.1:$Port"
  $acl = (Get-Acl $data).Access | ForEach-Object { $_.IdentityReference.Value }
  Check (-not ($acl -match 'Users$')) "the data folder is not readable by Users ($($acl -join ', '))"
  Check (($acl -contains "NT SERVICE\PennyWarden")) "the service account may write the data folder"
  Check ((Get-Item "$inst\current").Target -match [regex]::Escape($Version)) "current points at the new version"
  Check (Test-Path "$data\database") "PennyWarden created its database"

  # ---- upgrade (another version label from the same package): data kept, backup made, config untouched
  "marker" | Set-Content "$data\marker.txt"
  $cfgHash = (Get-FileHash "$data\config.toml").Hash
  $v2 = "$Version-test.999"
  $rc = Run-Installer @("-Version", "v$v2", "-ZipPath", $zipFull, "-NssmPath", $nssmFull)
  Check ($rc -eq 0) "upgrade exits with 0 (got $rc)"
  Check ((Get-Service PennyWarden).Status -eq "Running") "the service runs after the upgrade"
  Check ((Get-Item "$inst\current").Target -match [regex]::Escape($v2)) "current points at the upgraded version"
  Check (Test-Path "$inst\$Version") "the previous version is kept for a rollback"
  Check ((Get-Content "$data\marker.txt") -eq "marker") "the data is kept"
  Check ((Get-FileHash "$data\config.toml").Hash -eq $cfgHash) "config.toml is unchanged"
  $bak = Get-ChildItem "$data-upgrade-backups" -Directory | Select-Object -First 1
  Check ($null -ne $bak -and (Test-Path (Join-Path $bak.FullName "marker.txt"))) "the data was copied before the upgrade"
  $bacl = (Get-Acl "$data-upgrade-backups").Access | ForEach-Object { $_.IdentityReference.Value }
  Check (-not ($bacl -match 'Users$')) "the upgrade backups are not readable by Users"
  Check ((Invoke-RestMethod "http://127.0.0.1:$Port/api/health").status -eq "ok") "it answers after the upgrade"

  # ---- uninstall: services and program removed, data kept
  $rc = Run-Installer @("-Uninstall")
  Check ($rc -eq 0) "uninstall exits with 0 (got $rc)"
  Check ($null -eq (Get-Service PennyWarden -ErrorAction SilentlyContinue)) "the service is removed"
  Check (-not (Test-Path $inst)) "the program folder is removed"
  Check (Test-Path "$data\marker.txt") "the data folder is kept"
  Write-Host "SERVER INSTALLER TEST PASSED"
} catch {
  if (Test-Path "$data\logs\service.log") { Write-Host "--- service.log"; Get-Content "$data\logs\service.log" -Tail 40 }
  exit 1
} finally {
  if (Get-Service PennyWarden -ErrorAction SilentlyContinue) { & "$inst\nssm.exe" stop PennyWarden 2>$null; & "$inst\nssm.exe" remove PennyWarden confirm 2>$null }
}

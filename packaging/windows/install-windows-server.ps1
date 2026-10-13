<#
.SYNOPSIS
  PennyWarden install / upgrade / uninstall for a Windows server (2.0.0, #187).

.DESCRIPTION
  Run in PowerShell **as Administrator** (Windows Server 2022 or later, Windows 11):

    Invoke-WebRequest https://github.com/kretherford0983/PennyWarden/releases/latest/download/install-windows-server.ps1 -OutFile install-windows-server.ps1
    powershell -ExecutionPolicy Bypass -File .\install-windows-server.ps1 -Domain books.example.org

  What it does (docs/install-windows-server.md describes the same set-up by hand):
    * finds the release on GitHub (or uses -Version), downloads the Windows package and NSSM from that release and
      checks both against the release's SHA256SUMS.txt;
    * installs the program into <InstallDir>\<version> and points <InstallDir>\current at it (earlier versions stay
      for a rollback);
    * creates the data folder (default C:\ProgramData\PennyWarden) readable only by SYSTEM, Administrators and the
      service, and writes config.toml for server mode - an existing config.toml is never changed;
    * runs PennyWarden as the Windows service "PennyWarden" (NSSM) under the virtual account NT SERVICE\PennyWarden
      (no password to manage), started at boot and restarted if it stops;
    * with -Domain: installs Caddy (fixed version, SHA-256 checked) as the service "Caddy" in front of PennyWarden,
      which gets and renews the HTTPS certificate from Let's Encrypt, and opens ports 80 and 443 in the firewall.
      Without -Domain PennyWarden listens on 127.0.0.1 only, for a Cloudflare Tunnel or a front end you manage;
    * checks that PennyWarden answers.

  Running it again upgrades: the service is stopped, the data folder is copied to
  <DataDir>-upgrade-backups\<date-time>, the new version is installed next to the old one and started; if it does not
  answer, the previous version is put back. -Uninstall removes the services and the program and keeps the data.

.PARAMETER Version
  Install exactly this release, e.g. v2.0.0 or v2.0.0-test.130 (default: the newest release, see -Channel).
.PARAMETER Channel
  auto (default: the newest production release that has this installer; while there is none, the newest test build),
  production or test.
.PARAMETER Domain
  The web address people use (it must point at this server). Sets up Caddy for HTTPS.
.PARAMETER Email
  Optional contact address given to Let's Encrypt with -Domain (expiry notices).
.PARAMETER Port
  PennyWarden's local port (default: the port in an existing config.toml, else 8765).
.PARAMETER InstallDir
  Program folder (default C:\PennyWarden).
.PARAMETER DataDir
  Data folder (default C:\ProgramData\PennyWarden).
.PARAMETER ZipPath
  Use this PennyWarden-windows-x64.zip instead of downloading it (offline servers; needs -Version).
.PARAMETER NssmPath
  Use this nssm.exe instead of downloading it.
.PARAMETER CaddyPath
  Use this caddy.exe instead of downloading it.
.PARAMETER Uninstall
  Remove the services and the program folder. The data folder and upgrade backups are kept.
.PARAMETER Yes
  Do not ask before installing.
#>
[CmdletBinding()]
param(
  [string]$Version = "",
  [ValidateSet("auto", "production", "test")][string]$Channel = "auto",
  [string]$Domain = "",
  [string]$Email = "",
  [int]$Port = 0,
  [string]$InstallDir = "C:\PennyWarden",
  [string]$DataDir = "C:\ProgramData\PennyWarden",
  [string]$ZipPath = "",
  [string]$NssmPath = "",
  [string]$CaddyPath = "",
  [switch]$Uninstall,
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"          # Invoke-WebRequest is many times faster without the progress bar

$Repo = if ($env:PENNYWARDEN_REPO) { $env:PENNYWARDEN_REPO } else { "kretherford0983/PennyWarden" }
$Api = "https://api.github.com/repos/$Repo"
$Download = "https://github.com/$Repo/releases/download"
$Service = "PennyWarden"
$ServiceAccount = "NT SERVICE\PennyWarden"
$CaddyService = "Caddy"
# Caddy is downloaded from its own GitHub release at this version and must match this SHA-256 (#187).
$CaddyVersion = "2.11.7"
$CaddySha256 = "0a1edc0b799512051c57071ce0e798d3f2cf67dc98171366f1d2b326072e3b06"
$PackageName = "PennyWarden-windows-x64.zip"
$NssmName = "nssm.exe"
$MinProduction = [version]"2.0.0"                 # first production release that ships this installer

function Say([string]$m) { Write-Host "==> $m" }
function Note([string]$m) { Write-Host "    $m" }
function Fail([string]$m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------ checks
function Assert-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "run PowerShell as Administrator (right-click PowerShell -> Run as administrator), then run this script again."
  }
  if (-not [Environment]::Is64BitOperatingSystem) { Fail "PennyWarden needs 64-bit Windows." }
}

function Assert-Inputs {
  if ($Version -and $Version -notmatch '^v\d+\.\d+\.\d+(-test\.\d+)?$') { Fail "-Version must look like v2.0.0 or v2.0.0-test.130" }
  if ($Domain -and $Domain -notmatch '^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$') {
    Fail "-Domain must be a web address such as books.example.org (no https://, no path)."
  }
  if ($Email -and $Email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { Fail "-Email is not an email address." }
  if ($Port -and ($Port -lt 1 -or $Port -gt 65535)) { Fail "-Port must be between 1 and 65535." }
  if ($ZipPath -and -not $Version) { Fail "-ZipPath needs -Version (the version in the zip, e.g. v2.0.0)." }
  foreach ($p in @($ZipPath, $NssmPath, $CaddyPath)) { if ($p -and -not (Test-Path -LiteralPath $p -PathType Leaf)) { Fail "file not found: $p" } }
  foreach ($d in @($InstallDir, $DataDir)) {
    if (-not [IO.Path]::IsPathRooted($d)) { Fail "use a full path such as C:\PennyWarden (got '$d')." }
  }
}

# ------------------------------------------------------------------ downloads
function Get-File([string]$Url, [string]$Out) {
  for ($i = 1; $i -le 4; $i++) {
    try { Invoke-WebRequest -Uri $Url -OutFile $Out -UseBasicParsing -Headers @{ "User-Agent" = "PennyWarden-installer" }; return }
    catch { if ($i -eq 4) { Fail "could not download $Url ($($_.Exception.Message))" }; Start-Sleep -Seconds (3 * $i) }
  }
}

function Get-Json([string]$Url) {
  try { return Invoke-RestMethod -Uri $Url -UseBasicParsing -Headers @{ "User-Agent" = "PennyWarden-installer"; "Accept" = "application/vnd.github+json" } }
  catch { Fail "could not read $Url ($($_.Exception.Message))" }
}

function Get-Sha256([string]$File) { (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant() }

function Assert-Hash([string]$File, [string]$Expected, [string]$What) {
  $got = Get-Sha256 $File
  if ($got -ne $Expected.ToLowerInvariant()) { Fail "$What does not match its checksum (got $got, expected $Expected). Nothing was changed." }
  Note "$What checksum OK"
}

function Read-Sums([string]$File) {
  $sums = @{}
  foreach ($line in Get-Content -LiteralPath $File) {
    if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') { $sums[$Matches[2]] = $Matches[1].ToLowerInvariant() }
  }
  return $sums
}

function Test-HasAsset($rel, [string]$name) { return @($rel.assets | Where-Object { $_.name -eq $name }).Count -gt 0 }

function Resolve-Tag {
  if ($Version) { return $Version }
  $rels = @(Get-Json "$Api/releases?per_page=50") | Where-Object { -not $_.draft -and (Test-HasAsset $_ "install-windows-server.ps1") }
  $prod = @($rels | Where-Object { -not $_.prerelease -and $_.tag_name -match '^v(\d+\.\d+\.\d+)$' -and [version]$Matches[1] -ge $MinProduction })
  $test = @($rels | Where-Object { $_.prerelease -and $_.tag_name -match '^v\d+\.\d+\.\d+-test\.\d+$' })
  $sortKey = { $t = $_.tag_name -replace '^v', ''; $p = $t -split '-test\.'; [version]$p[0] }
  $buildKey = { if ($_.tag_name -match '-test\.(\d+)$') { [int]$Matches[1] } else { 0 } }
  $prod = @($prod | Sort-Object -Property $sortKey -Descending)
  $test = @($test | Sort-Object -Property @{ Expression = $sortKey; Descending = $true }, @{ Expression = $buildKey; Descending = $true })
  switch ($Channel) {
    "production" { if (-not $prod) { Fail "no production release with this installer yet; use -Channel test" }; return $prod[0].tag_name }
    "test" { if (-not $test) { Fail "no test build with this installer found" }; return $test[0].tag_name }
    default {
      if ($prod) { return $prod[0].tag_name }
      if (-not $test) { Fail "no release with this installer found" }
      Note "No production release with this installer yet: installing the newest TEST build $($test[0].tag_name)."
      Note "Use -Channel production to refuse this."
      return $test[0].tag_name
    }
  }
}

# ------------------------------------------------------------------ helpers
function Get-Svc([string]$Name) { Get-Service -Name $Name -ErrorAction SilentlyContinue }

function Stop-Svc([string]$Name) {
  $s = Get-Svc $Name
  if ($s -and $s.Status -ne "Stopped") { Say "Stopping the $Name service"; Stop-Service -Name $Name -Force; (Get-Svc $Name).WaitForStatus("Stopped", [TimeSpan]::FromSeconds(60)) }
}

function Invoke-Native([string]$Exe, [string[]]$ExeArgs) {
  # Windows PowerShell 5.1 turns anything a program writes to stderr into an error that "Stop" would throw: run
  # native programs with "Continue" and judge them by their exit code only.
  $eap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { $out = (& $Exe @ExeArgs 2>&1 | ForEach-Object { "$_" }) -join " "; return @{ Code = $LASTEXITCODE; Out = $out } }
  finally { $ErrorActionPreference = $eap }
}

function Invoke-Nssm([string]$Nssm, [string[]]$NssmArgs) {
  $r = Invoke-Native $Nssm $NssmArgs
  if ($r.Code -ne 0) { Fail "nssm $($NssmArgs -join ' ') failed: $($r.Out)" }
}

function Set-Link([string]$Link, [string]$Target) {
  if (Test-Path -LiteralPath $Link) { Invoke-Native "cmd.exe" @("/c", "rmdir", "$Link") | Out-Null }
  $r = Invoke-Native "cmd.exe" @("/c", "mklink", "/J", "$Link", "$Target")
  if ($r.Code -ne 0) { Fail "could not create the link $Link -> ${Target}: $($r.Out)" }
}

function Get-LinkTarget([string]$Link) {
  if (-not (Test-Path -LiteralPath $Link)) { return $null }
  $i = Get-Item -LiteralPath $Link -Force
  if ($i.Target) { return @($i.Target)[0] }
  return $null
}

function Protect-Folder([string]$Dir, [switch]$AdminsOnly) {
  # SYSTEM and Administrators: full control; the service account: modify (not for upgrade backups). Nothing inherited
  # from ProgramData (which lets every user read).
  $grants = @("*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F")
  if (-not $AdminsOnly) { $grants += "${ServiceAccount}:(OI)(CI)M" }
  $r = Invoke-Native "icacls.exe" (@("$Dir", "/inheritance:r", "/grant:r") + $grants)
  if ($r.Code -ne 0) { Fail "could not set the permissions of ${Dir}: $($r.Out)" }
}

function Read-ConfigPort([string]$Cfg) {
  if (-not (Test-Path -LiteralPath $Cfg)) { return 0 }
  $inServer = $false
  foreach ($line in Get-Content -LiteralPath $Cfg) {
    if ($line -match '^\s*\[([^\]]+)\]') { $inServer = $Matches[1].Trim() -eq "server"; continue }
    if ($inServer -and $line -match '^\s*port\s*=\s*(\d+)') { return [int]$Matches[1] }
  }
  return 0
}

function Wait-Healthy([int]$P, [int]$Seconds = 120) {
  for ($i = 0; $i -lt $Seconds; $i++) {
    try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:$P/api/health" -UseBasicParsing -TimeoutSec 3; if ($h.status -eq "ok") { return $true } } catch { }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Show-LogTail {
  $log = Join-Path $DataDir "logs\service.log"
  if (Test-Path -LiteralPath $log) { Write-Host "--- last lines of $log"; Get-Content -LiteralPath $log -Tail 30 }
}

# ------------------------------------------------------------------ uninstall
function Invoke-Uninstall {
  Say "Removing PennyWarden from this server (the data folder $DataDir is kept)"
  $nssm = Join-Path $InstallDir "nssm.exe"
  foreach ($name in @($Service, $CaddyService)) {
    $s = Get-Svc $name
    if (-not $s) { continue }
    if ($name -eq $CaddyService) {
      $path = (Get-CimInstance Win32_Service -Filter "Name='$name'").PathName
      if ($path -notlike "*$InstallDir*") { Note "The Caddy service was not installed by this script - left alone."; continue }
    }
    Stop-Svc $name
    if (Test-Path -LiteralPath $nssm) { Invoke-Nssm $nssm @("remove", $name, "confirm") } else { Invoke-Native "sc.exe" @("delete", $name) | Out-Null }
    Note "service $name removed"
  }
  Get-NetFirewallRule -DisplayName "PennyWarden HTTPS (Caddy)" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  if (Test-Path -LiteralPath $InstallDir) {
    $link = Join-Path $InstallDir "current"
    if (Test-Path -LiteralPath $link) { Invoke-Native "cmd.exe" @("/c", "rmdir", "$link") | Out-Null }
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Note "program folder $InstallDir removed"
  }
  Say "Done. Your data is still in $DataDir (and earlier upgrade backups in $DataDir-upgrade-backups)."
  exit 0
}

# ------------------------------------------------------------------ install / upgrade
Assert-Admin
Assert-Inputs
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
if ($Uninstall) { Invoke-Uninstall }

$cfg = Join-Path $DataDir "config.toml"
$upgrade = Test-Path -LiteralPath (Join-Path $DataDir "database")
if (-not $Port) { $Port = Read-ConfigPort $cfg }
if (-not $Port) { $Port = 8765 }

$tag = if ($ZipPath) { $Version } else { Resolve-Tag }
$folder = $tag -replace '^v', ''
$target = Join-Path $InstallDir $folder
$link = Join-Path $InstallDir "current"
$previous = Get-LinkTarget $link

Say "PennyWarden $tag - $(if ($upgrade) { 'upgrade' } else { 'new installation' }) on this server"
Note "program: $target"
Note "data:    $DataDir"
Note "service: $Service ($ServiceAccount), http://127.0.0.1:$Port"
if ($Domain) { Note "HTTPS:   https://$Domain (Caddy $CaddyVersion, Let's Encrypt)" } else { Note "HTTPS:   none set up here (a Cloudflare Tunnel or your own front end connects to 127.0.0.1:$Port)" }
if (-not $Yes) {
  $a = Read-Host "Continue? [Y/n]"
  if ($a -and $a -notmatch '^[Yy]') { Say "Nothing was changed."; exit 0 }
}

$work = Join-Path ([IO.Path]::GetTempPath()) ("pennywarden-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  # ---- 1. files, all checked before anything is changed
  Say "Getting the files"
  $zip = Join-Path $work $PackageName
  $nssmFile = Join-Path $work $NssmName
  if (-not $ZipPath -or -not $NssmPath) {
    $sumsFile = Join-Path $work "SHA256SUMS.txt"
    Get-File "$Download/$tag/SHA256SUMS.txt" $sumsFile
    $sums = Read-Sums $sumsFile
  }
  if ($ZipPath) { Copy-Item -LiteralPath $ZipPath $zip; Note "using $ZipPath" }
  else { Get-File "$Download/$tag/$PackageName" $zip; if (-not $sums.ContainsKey($PackageName)) { Fail "$PackageName is not in the release's SHA256SUMS.txt" }; Assert-Hash $zip $sums[$PackageName] $PackageName }
  if ($NssmPath) { Copy-Item -LiteralPath $NssmPath $nssmFile; Note "using $NssmPath" }
  else { Get-File "$Download/$tag/$NssmName" $nssmFile; if (-not $sums.ContainsKey($NssmName)) { Fail "$NssmName is not in the release's SHA256SUMS.txt" }; Assert-Hash $nssmFile $sums[$NssmName] $NssmName }
  $caddyFile = $null
  if ($Domain) {
    $caddyFile = Join-Path $work "caddy.exe"
    if ($CaddyPath) { Copy-Item -LiteralPath $CaddyPath $caddyFile; Note "using $CaddyPath" }
    else {
      $cz = Join-Path $work "caddy.zip"
      Get-File "https://github.com/caddyserver/caddy/releases/download/v$CaddyVersion/caddy_${CaddyVersion}_windows_amd64.zip" $cz
      Assert-Hash $cz $CaddySha256 "Caddy $CaddyVersion"
      Expand-Archive -LiteralPath $cz -DestinationPath (Join-Path $work "caddy") -Force
      Copy-Item (Join-Path $work "caddy\caddy.exe") $caddyFile
    }
  }
  $unz = Join-Path $work "pkg"
  Expand-Archive -LiteralPath $zip -DestinationPath $unz -Force
  $inner = Get-ChildItem -LiteralPath $unz -Directory | Where-Object { Test-Path (Join-Path $_.FullName "app\launch.py") } | Select-Object -First 1
  if (-not $inner) { if (Test-Path (Join-Path $unz "app\launch.py")) { $inner = Get-Item $unz } else { Fail "$PackageName does not contain app\launch.py" } }

  # ---- 2. stop, back up the data
  Stop-Svc $Service
  if ($upgrade) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $bakRoot = "$DataDir-upgrade-backups"
    $bak = Join-Path $bakRoot $stamp
    Say "Copying the data folder to $bak"
    New-Item -ItemType Directory -Path $bakRoot -Force | Out-Null
    Protect-Folder $bakRoot -AdminsOnly            # before copying: the copy holds the database and the key
    Copy-Item -LiteralPath $DataDir -Destination $bak -Recurse -Force
  }

  # ---- 3. program
  Say "Installing the program"
  New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  if (Test-Path -LiteralPath $target) {
    if ($previous -and ((Resolve-Path $previous).Path -eq (Resolve-Path $target).Path)) { $previous = $null }   # reinstall of the same version
    Remove-Item -LiteralPath $target -Recurse -Force
  }
  Move-Item -LiteralPath $inner.FullName -Destination $target
  Set-Link $link $target
  Copy-Item -LiteralPath $nssmFile (Join-Path $InstallDir $NssmName) -Force
  $nssm = Join-Path $InstallDir $NssmName

  # ---- 4. data folder and config.toml
  New-Item -ItemType Directory -Path (Join-Path $DataDir "logs") -Force | Out-Null
  if (-not (Test-Path -LiteralPath $cfg)) {
    Say "Writing $cfg"
    $hsts = if ($Domain) { "true" } else { "false" }
    $lines = @(
      "# PennyWarden settings (docs/configuration.md). Written by install-windows-server.ps1; the installer never",
      "# changes this file again. Administrators can change the security settings in System/About -> Settings.",
      "[server]",
      "mode = `"server`"",
      "host = `"127.0.0.1`"          # only this computer: Caddy or a tunnel connects here",
      "port = $Port",
      "secure_cookies = `"true`"     # people reach PennyWarden over HTTPS",
      "hsts = $hsts",
      "trusted_proxies = `"127.0.0.1`"",
      "# folders an Administrator may choose for scheduled backups, e.g. [`"D:\\PennyWarden-backups`"]",
      "backup_folders = []"
    )
    [IO.File]::WriteAllText($cfg, ($lines -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding($false)))
  } else { Note "keeping the existing $cfg" }

  # ---- 5. the service
  $python = Join-Path $link "python\python.exe"
  $launch = Join-Path $link "app\launch.py"
  if (-not (Get-Svc $Service)) { Say "Creating the $Service service"; Invoke-Nssm $nssm @("install", $Service, $python) }
  else { Say "Updating the $Service service"; Invoke-Nssm $nssm @("set", $Service, "Application", $python) }
  $log = Join-Path $DataDir "logs\service.log"
  Invoke-Nssm $nssm @("set", $Service, "AppParameters", "-I `"$launch`" --mode server --no-browser --data-dir `"$DataDir`"")
  Invoke-Nssm $nssm @("set", $Service, "AppDirectory", $link)
  Invoke-Nssm $nssm @("set", $Service, "AppEnvironmentExtra", "PYTHONNOUSERSITE=1", "PYTHONDONTWRITEBYTECODE=1")
  Invoke-Nssm $nssm @("set", $Service, "DisplayName", "PennyWarden")
  Invoke-Nssm $nssm @("set", $Service, "Description", "PennyWarden bookkeeping (server mode)")
  Invoke-Nssm $nssm @("set", $Service, "Start", "SERVICE_AUTO_START")
  Invoke-Nssm $nssm @("set", $Service, "AppExit", "Default", "Restart")
  Invoke-Nssm $nssm @("set", $Service, "AppRestartDelay", "3000")
  Invoke-Nssm $nssm @("set", $Service, "AppStdout", $log)
  Invoke-Nssm $nssm @("set", $Service, "AppStderr", $log)
  Invoke-Nssm $nssm @("set", $Service, "AppRotateFiles", "1")
  Invoke-Nssm $nssm @("set", $Service, "AppRotateBytes", "5000000")
  $r = Invoke-Native "sc.exe" @("config", $Service, "obj=", $ServiceAccount)
  if ($r.Code -ne 0) { Fail "could not set the service account: $($r.Out)" }
  Protect-Folder $DataDir

  # ---- 6. HTTPS with Caddy
  if ($Domain) {
    Say "Setting up Caddy for https://$Domain"
    $cdir = Join-Path $InstallDir "caddy"
    New-Item -ItemType Directory -Path (Join-Path $cdir "data") -Force | Out-Null
    Stop-Svc $CaddyService
    Copy-Item -LiteralPath $caddyFile (Join-Path $cdir "caddy.exe") -Force
    $global = if ($Email) { "{`r`n`temail $Email`r`n}`r`n`r`n" } else { "" }
    $caddyfile = "$global$Domain {`r`n`treverse_proxy 127.0.0.1:$Port`r`n}`r`n"
    [IO.File]::WriteAllText((Join-Path $cdir "Caddyfile"), $caddyfile, (New-Object Text.UTF8Encoding($false)))
    $cexe = Join-Path $cdir "caddy.exe"
    if (-not (Get-Svc $CaddyService)) { Invoke-Nssm $nssm @("install", $CaddyService, $cexe) } else { Invoke-Nssm $nssm @("set", $CaddyService, "Application", $cexe) }
    Invoke-Nssm $nssm @("set", $CaddyService, "AppParameters", "run --config `"$(Join-Path $cdir 'Caddyfile')`" --adapter caddyfile")
    Invoke-Nssm $nssm @("set", $CaddyService, "AppDirectory", $cdir)
    Invoke-Nssm $nssm @("set", $CaddyService, "AppEnvironmentExtra", "XDG_DATA_HOME=$(Join-Path $cdir 'data')", "XDG_CONFIG_HOME=$(Join-Path $cdir 'data')")
    Invoke-Nssm $nssm @("set", $CaddyService, "DisplayName", "Caddy (HTTPS for PennyWarden)")
    Invoke-Nssm $nssm @("set", $CaddyService, "Start", "SERVICE_AUTO_START")
    Invoke-Nssm $nssm @("set", $CaddyService, "AppStdout", (Join-Path $cdir "caddy.log"))
    Invoke-Nssm $nssm @("set", $CaddyService, "AppStderr", (Join-Path $cdir "caddy.log"))
    if (-not (Get-NetFirewallRule -DisplayName "PennyWarden HTTPS (Caddy)" -ErrorAction SilentlyContinue)) {
      New-NetFirewallRule -DisplayName "PennyWarden HTTPS (Caddy)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 80, 443 | Out-Null
      Note "firewall: ports 80 and 443 opened"
    }
  } elseif (Get-Svc $CaddyService) { Note "The Caddy service exists already and was left as it is (no -Domain given)." }

  # ---- 7. start and check
  Say "Starting PennyWarden"
  Start-Service -Name $Service
  if (-not (Wait-Healthy $Port)) {
    Show-LogTail
    if ($previous -and (Test-Path -LiteralPath $previous)) {
      Write-Host "PennyWarden $tag did not answer - putting back the previous version ($previous)." -ForegroundColor Yellow
      Stop-Svc $Service
      Set-Link $link $previous
      Start-Service -Name $Service
      if (Wait-Healthy $Port) { Fail "the upgrade to $tag failed; the previous version is running again. The data copy is in $bak." }
      Fail "the upgrade to $tag failed and the previous version did not start either. The data copy is in $bak."
    }
    Fail "PennyWarden did not answer on port $Port. See the log above and docs/install-windows-server.md -> Troubleshooting."
  }
  $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/system/status" -UseBasicParsing
  Note "PennyWarden $($st.version) answers in $($st.mode) mode"
  if ($Domain) { Start-Service -Name $CaddyService }

  # ---- 8. tidy up: keep the previous version for a rollback, remove older ones
  $keep = @((Resolve-Path $target).Path)
  if ($previous -and (Test-Path -LiteralPath $previous)) { $keep += (Resolve-Path $previous).Path }
  Get-ChildItem -LiteralPath $InstallDir -Directory | Where-Object {
    $_.Name -match '^\d+\.\d+\.\d+(-test\.\d+)?$' -and $keep -notcontains $_.FullName
  } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Note "removed old version $($_.Name)" }

  Write-Host ""
  Say "PennyWarden $tag is installed and running."
  if ($Domain) {
    Note "Open https://$Domain (the certificate can take a minute the first time; $Domain must point at this server"
    Note "and ports 80 and 443 must reach it)."
  } else {
    Note "PennyWarden listens on http://127.0.0.1:$Port - point your Cloudflare Tunnel or front end at it."
  }
  if (-not $upgrade) { Note "The first visit shows the setup wizard: the organization and the first Administrator (with two-step verification)." }
  else { Note "The data copy from before the upgrade is in $bak." }
  Note "Host commands: $link\PennyWarden.cmd restore|reinitialize|reset-password ... --data-dir $DataDir"
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

# Backup of StudentCV PostgreSQL database.
#
# ASCII-only on purpose: non-ASCII characters in .ps1 break parsing on this machine.
# Custom format (-Fc) with compression; restore with scripts/restore.ps1
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/backup.ps1 [-Keep 10]

param(
    [int]$Keep = 10
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

$BackupDir = Join-Path (Get-Location) 'backups'
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

# Read DB credentials from .env
$EnvFile = Join-Path (Get-Location) '.env'
if (-not (Test-Path $EnvFile)) {
    throw ".env not found. Copy .env.example to .env and fill it in."
}

$Vars = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
        $parts = $line.Split('=', 2)
        $Vars[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$DbUser = $Vars['POSTGRES_USER']
$DbName = $Vars['POSTGRES_DB']
if (-not $DbUser -or -not $DbName) {
    throw "POSTGRES_USER or POSTGRES_DB missing in .env"
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutFile = Join-Path $BackupDir "studentcv-$Stamp.dump"

# The dump is written inside the container and copied out afterwards.
# Redirecting the binary stream through cmd.exe (pg_dump > file) is fragile:
# PowerShell 5.1 rewrites binary output, and cmd's redirection is not
# guaranteed to be byte-exact across shells.
$Shell = "pg_dump -U $DbUser -d $DbName -Fc -f /tmp/backup.dump"
$PrevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
docker compose exec -T db sh -c $Shell 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

Write-Host "Dumping to $OutFile"
docker compose cp db:/tmp/backup.dump $OutFile 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Copying the dump out of the container failed"
}
$ErrorActionPreference = $PrevPref

if (-not (Test-Path $OutFile)) {
    throw "Dump file was not created: $OutFile"
}

$Size = (Get-Item $OutFile).Length
if ($Size -lt 1024) {
    throw "Dump file is suspiciously small ($Size bytes) - treat it as broken."
}

# A valid custom-format dump starts with the PGDMP magic header.
$Header = [System.Text.Encoding]::ASCII.GetString(
    [System.IO.File]::ReadAllBytes($OutFile)[0..4]
)
if ($Header -ne 'PGDMP') {
    throw "Dump file has no PGDMP header (got '$Header') - the file is broken."
}

Write-Host ("OK: {0} ({1:N0} bytes)" -f $OutFile, $Size)

# Rotation: keep the newest $Keep dumps
$Old = Get-ChildItem -Path $BackupDir -Filter 'studentcv-*.dump' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep
foreach ($f in $Old) {
    Write-Host "Removing old backup: $($f.Name)"
    Remove-Item $f.FullName -Force
}

Write-Host "Backup finished. Files in ${BackupDir}:"
Get-ChildItem -Path $BackupDir -Filter 'studentcv-*.dump' |
    Sort-Object LastWriteTime -Descending |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize

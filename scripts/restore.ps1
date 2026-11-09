# Restore StudentCV PostgreSQL database from a dump created by scripts/backup.ps1.
#
# ASCII-only on purpose: non-ASCII characters in .ps1 break parsing on this machine.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/restore.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/restore.ps1 -File backups/studentcv-20261108-120000.dump
#
# WARNING: restore replaces the current content of the database.

param(
    [string]$File = ''
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

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

# Pick the newest dump if no file was given
if (-not $File) {
    $Newest = Get-ChildItem -Path (Join-Path (Get-Location) 'backups') -Filter 'studentcv-*.dump' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $Newest) {
        throw "No dump found in ./backups and -File was not specified."
    }
    $File = $Newest.FullName
}

if (-not (Test-Path $File)) {
    throw "Dump file not found: $File"
}

Write-Host "Restoring from $File into database $DbName"

# The dump is copied into the container and restored from there.
# Piping it through cmd.exe (type | pg_restore) corrupts the binary bytes,
# and pg_restore then rejects the archive.
$PrevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
docker compose cp $File db:/tmp/restore.dump 2>&1 | Out-Null

$Shell = "pg_restore -U $DbUser -d $DbName --clean --if-exists --no-owner /tmp/restore.dump"
docker compose exec -T db sh -c $Shell 2>&1 | Out-Null
$code = $LASTEXITCODE
$ErrorActionPreference = $PrevPref

if ($code -ne 0) {
    throw "pg_restore failed with exit code $code"
}

Write-Host "Restore finished."

# Quick verification
$Shell = "psql -U $DbUser -d $DbName -t -A -c 'select count(*) from students'"
docker compose exec -T db sh -c $Shell 2>&1 | Out-Null

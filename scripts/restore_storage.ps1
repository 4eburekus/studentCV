# Restore the StudentCV object storage from a dump made by backup_storage.ps1.
#
# ASCII-only on purpose: non-ASCII characters in .ps1 break parsing here.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/restore_storage.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/restore_storage.ps1 -Dir backups\storage-20261110-181500
#   powershell -ExecutionPolicy Bypass -File scripts/restore_storage.ps1 -VerifyOnly
#
# Without -Dir the newest backups\storage-* is used.
#
# WARNING: objects are written back into the live buckets. Restoring over an
# existing object does not destroy the previous version while versioning is
# enabled, but the DATABASE still decides which keys are current - restore the
# database dump too (scripts/restore.ps1), otherwise keys and bytes diverge.

param(
    [string]$Dir = '',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

$BackupRoot = Join-Path (Get-Location) 'backups'

if (-not $Dir) {
    $Newest = Get-ChildItem -Path $BackupRoot -Directory -Filter 'storage-*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $Newest) {
        throw "No storage dump found in .\backups and -Dir was not specified."
    }
    $Dir = $Newest.FullName
}

if (-not (Test-Path (Join-Path $Dir 'manifest.json'))) {
    throw "manifest.json not found in $Dir - this is not a storage dump."
}

# The tool reads the same /backups bind mount the dump was written to, so the
# path passed to the container is the container-side one.
$Leaf = Split-Path $Dir -Leaf
$RemoteDir = '/backups/' + $Leaf

$PrevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'

if ($VerifyOnly) {
    Write-Host "Verifying checksums of $Dir"
    docker compose exec -T backend python -m app.tools.storage_backup verify --dir $RemoteDir 2>&1 | Out-String | Write-Host
} else {
    Write-Host "Restoring objects from $Dir"
    docker compose exec -T backend python -m app.tools.storage_backup restore --dir $RemoteDir 2>&1 | Out-String | Write-Host
}
$code = $LASTEXITCODE
$ErrorActionPreference = $PrevPref

if ($code -ne 0) {
    throw "storage restore failed with exit code $code"
}

Write-Host ""
Write-Host "Storage restore finished. Keys are decided by the database: if you did"
Write-Host "not restore scripts/backup.ps1 as well, run the consistency check"
Write-Host "(app.services.photos.verify_objects lists keys with no object in the bucket)."

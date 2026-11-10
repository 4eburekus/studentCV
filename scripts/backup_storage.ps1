# Backup of the StudentCV object storage (S3-compatible: SeaweedFS).
#
# ASCII-only on purpose: non-ASCII characters in .ps1 break parsing here.
#
# The dump is produced inside the backend container by
# python -m app.tools.storage_backup and written straight into /backups, which
# is a bind mount of ./backups (compose.override.yaml). Two reasons for that:
#   - a dump in the container's /tmp dies with `docker compose down -v`
#     (we lost one dump exactly that way);
#   - the tool talks S3, so it does not care which storage product is behind
#     the endpoint.
#
# Storage dump is only half of a backup: object keys live in the database
# (student_photos). Restore both, or you get orphaned objects and references
# to missing ones.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/backup_storage.ps1 [-Keep 5]

param(
    [int]$Keep = 5
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

$BackupRoot = Join-Path (Get-Location) 'backups'
if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot | Out-Null
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = 'storage-' + $Stamp
$LocalDir = Join-Path $BackupRoot $Name

# docker writes progress to stderr; with ErrorActionPreference=Stop a
# successful command would abort the script.
$PrevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'

Write-Host "Dumping object storage into $LocalDir"
docker compose exec -T backend python -m app.tools.storage_backup dump --dir /backups/$Name 2>&1 | Out-String | Write-Host
$code = $LASTEXITCODE
$ErrorActionPreference = $PrevPref

if ($code -ne 0) {
    throw "storage dump failed with exit code $code"
}

# --- Verification -------------------------------------------------------------
# A dump you cannot read is not a backup: manifest must exist and parse, and
# every listed object must be on disk.
$ManifestPath = Join-Path $LocalDir 'manifest.json'
if (-not (Test-Path $ManifestPath)) {
    throw "manifest.json is missing in $LocalDir"
}

$Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
if (-not $Manifest.total_objects) {
    throw 'manifest.json has no total_objects - it is corrupt'
}

$Missing = 0
foreach ($bucket in $Manifest.buckets.PSObject.Properties.Name) {
    foreach ($entry in $Manifest.buckets.$bucket) {
        if (-not (Test-Path (Join-Path $LocalDir ($bucket + '\' + $entry.file)))) {
            $Missing++
        }
    }
}
if ($Missing -ne 0) {
    throw "dump incomplete: $Missing objects listed in manifest are missing on disk"
}

Write-Host ("OK: {0} objects ({1} buckets) in {2}" -f
    $Manifest.total_objects, $Manifest.buckets.PSObject.Properties.Name.Count, $LocalDir)

# Rotation: keep the newest $Keep dump directories.
$Old = Get-ChildItem -Path $BackupRoot -Directory -Filter 'storage-*' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep
foreach ($d in $Old) {
    Write-Host "Removing old storage backup: $($d.Name)"
    Remove-Item $d.FullName -Recurse -Force
}

Write-Host ""
Write-Host "Pair this dump with scripts/backup.ps1: keys live in student_photos,"
Write-Host "so restore both (restore.ps1 then restore_storage.ps1)."

# Smoke tests for the StudentCV schema: constraints, uniqueness, cascade.
#
# ASCII-only on purpose: non-ASCII characters in .ps1 break parsing on this machine.
# Cyrillic test data is built from char codes at runtime and passed to psql
# through a UTF-8 file on stdin (not via the command line, to keep the bytes intact).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1

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

$script:Failures = 0

function Invoke-Sql {
    <#
      Runs a SQL script inside the db container and returns combined output.

      The SQL file is copied into the container and the result is written to a
      file inside the container as well. Both steps go through docker's binary
      stream: piping Cyrillic through cmd.exe corrupts the bytes (PS 5.1
      writes the console codepage, not UTF-8).
    #>
    param([string]$Sql)

    $TmpFile = Join-Path $env:TEMP ("smoke-" + [guid]::NewGuid().ToString('N') + ".sql")
    $OutFile = Join-Path $env:TEMP ("smoke-out-" + [guid]::NewGuid().ToString('N') + ".txt")
    $Utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($TmpFile, $Sql, $Utf8)
    # docker writes progress to stderr; with ErrorActionPreference=Stop that would
    # abort the script, so stderr is silenced inside this function only.
    $PrevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        docker compose cp $TmpFile db:/tmp/smoke.sql 2>&1 | Out-Null

        $Shell = "psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -t -A -f /tmp/smoke.sql > /tmp/smoke_out.txt 2>&1"
        docker compose exec -T db sh -c $Shell 2>&1 | Out-Null
        $code = $LASTEXITCODE

        docker compose cp db:/tmp/smoke_out.txt $OutFile 2>&1 | Out-Null
        $text = ''
        if (Test-Path $OutFile) {
            $text = [System.IO.File]::ReadAllText($OutFile, $Utf8)
        }

        return [pscustomobject]@{
            Output = $text
            ExitCode = $code
        }
    }
    finally {
        $ErrorActionPreference = $PrevPref
        Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
        Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
    }
}

function Assert-SqlOk {
    param([string]$Name, [string]$Sql)
    $r = Invoke-Sql $Sql
    if ($r.ExitCode -eq 0) {
        Write-Host "PASS  $Name"
    }
    else {
        $script:Failures++
        Write-Host "FAIL  $Name"
        Write-Host ($r.Output)
    }
}

function Assert-SqlFails {
    param([string]$Name, [string]$Sql, [string]$Expect = '')
    $r = Invoke-Sql $Sql
    if ($r.ExitCode -ne 0 -and ($Expect -eq '' -or $r.Output -match $Expect)) {
        Write-Host "PASS  $Name (rejected as expected)"
    }
    else {
        $script:Failures++
        Write-Host "FAIL  $Name - expected failure, got exit code $($r.ExitCode)"
        Write-Host ($r.Output)
    }
}

# --- Cyrillic test data built from char codes ---------------------------------
# "FIItt" -> 01-FIItt-01 (valid)
$validGroup = "01-" + [char]0x0424 + [char]0x0418 + [char]0x0418 + [char]0x0442 + [char]0x0442 + "-01"
# 01-fiitt-01 - lowercase, invalid
$lowerGroup = "01-" + [char]0x0444 + [char]0x0438 + [char]0x0438 + [char]0x0442 + [char]0x0442 + "-01"
# 01-FItt-01 - only two capital letters, invalid
$shortGroup = "01-" + [char]0x0424 + [char]0x0418 + [char]0x0442 + [char]0x0442 + "-01"
# Dedicated group for the cascade test, so it does not touch attendance rows
$cascadeGroup = "09-" + [char]0x0426 + [char]0x041A + [char]0x0410 + [char]0x0446 + [char]0x0446 + "-09"

Write-Host "=== StudentCV smoke tests ==="
Write-Host "valid group   : $validGroup"
Write-Host "invalid (low) : $lowerGroup"
Write-Host "invalid (2 up): $shortGroup"
Write-Host ""

# --- 1. group_number CHECK ---------------------------------------------------
Assert-SqlOk "insert student with valid group number" @"
insert into students (full_name, group_number)
select 'Smoke Test Student', '$validGroup'
where not exists (
    select 1 from students where group_number = '$validGroup'
);
"@

Assert-SqlFails "reject lowercase group number" @"
insert into students (full_name, group_number)
select 'Smoke Bad Lower', '$lowerGroup'
where not exists (
    select 1 from students where group_number = '$lowerGroup'
);
"@ 'students_group_number_format'

Assert-SqlFails "reject group number with 2 capital letters" @"
insert into students (full_name, group_number)
select 'Smoke Bad Short', '$shortGroup'
where not exists (
    select 1 from students where group_number = '$shortGroup'
);
"@ 'students_group_number_format'

# --- 2. LATE requires delay_minutes -----------------------------------------
# The test creates its own lesson, so it does not depend on the seeds being loaded.
Assert-SqlOk "create test discipline and lesson" @"
insert into disciplines (name, teacher_id)
select 'Smoke Discipline', id from teachers order by id limit 1;

insert into lessons (discipline_id, lesson_date, start_time, end_time)
select d.id, current_date + 60, time '08:30', time '10:00'
from disciplines d
where d.name = 'Smoke Discipline'
  and not exists (
      select 1 from lessons l
      where l.discipline_id = d.id
        and l.lesson_date = current_date + 60
        and l.start_time = time '08:30'
  );
"@

Assert-SqlFails "reject LATE without delay_minutes" @"
insert into attendance_records (student_id, lesson_id, entry_time, status)
select s.id, l.id, now(), 'LATE'
from students s, lessons l
where s.group_number = '$validGroup'
  and l.discipline_id = (select id from disciplines where name = 'Smoke Discipline' limit 1)
  and not exists (
      select 1 from attendance_records
      where student_id = s.id and lesson_id = l.id
  );
"@ 'late_iff_delay_present'

Assert-SqlOk "accept LATE with delay_minutes" @"
insert into attendance_records (student_id, lesson_id, entry_time, status, delay_minutes)
select s.id, l.id, now(), 'LATE', 12
from students s, lessons l
where s.group_number = '$validGroup'
  and l.discipline_id = (select id from disciplines where name = 'Smoke Discipline' limit 1)
  and not exists (
      select 1 from attendance_records
      where student_id = s.id and lesson_id = l.id
  );
"@

# --- 3. UNIQUE (student_id, lesson_id) --------------------------------------
Assert-SqlFails "reject duplicate attendance for the same student and lesson" @"
insert into attendance_records (student_id, lesson_id, entry_time, status)
select s.id, l.id, now(), 'PRESENT'
from students s, lessons l
where s.group_number = '$validGroup'
  and l.discipline_id = (select id from disciplines where name = 'Smoke Discipline' limit 1)
  and exists (
      select 1 from attendance_records
      where student_id = s.id and lesson_id = l.id
  );
"@ 'uq_attendance_records_student_lesson'

# --- 4. ON DELETE CASCADE for student_photos ---------------------------------
Assert-SqlOk "insert student and photo for cascade test" @"
insert into students (full_name, group_number)
select 'Smoke Cascade Student', '$cascadeGroup'
where not exists (
    select 1 from students where group_number = '$cascadeGroup'
);

insert into student_photos (student_id, photo_url)
select id, 'biometrics/smoke-cascade.jpg'
from students
where group_number = '$cascadeGroup'
  and not exists (
      select 1 from student_photos where photo_url = 'biometrics/smoke-cascade.jpg'
  );
"@

Assert-SqlOk "delete student cascades to photos" @"
delete from students where group_number = '$cascadeGroup';
"@

$r = Invoke-Sql "select count(*) from student_photos where photo_url = 'biometrics/smoke-cascade.jpg';"
if ($r.Output.Trim() -eq '0') {
    Write-Host "PASS  photos removed together with the student"
}
else {
    $script:Failures++
    Write-Host "FAIL  photos were not cascaded"
}

# --- 5. lesson time CHECK ----------------------------------------------------
Assert-SqlFails "reject lesson with end_time <= start_time" @"
insert into lessons (discipline_id, lesson_date, start_time, end_time)
select d.id, current_date + 90, time '10:00', time '09:00'
from disciplines d
where d.name = 'Smoke Discipline'
limit 1;
"@ 'end_after_start'

Write-Host ""
if ($script:Failures -eq 0) {
    Write-Host "ALL SMOKE TESTS PASSED"
    exit 0
}
else {
    Write-Host "$($script:Failures) SMOKE TEST(S) FAILED"
    exit 1
}

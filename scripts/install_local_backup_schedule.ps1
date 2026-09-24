param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = (Get-Command $Python -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.local-server\production\compose.yaml'))) {
    throw 'Initialize the production local stack first.'
}
$ScriptPath = Join-Path $ProjectRoot 'scripts\local_backup.py'
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument ('-B "' + $ScriptPath + '" backup --stage production') -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At '03:00'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -Hidden
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'KnowMate-Local-Backup' -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Encrypted cold backup of the isolated local production stack. Brief maintenance pause at 03:00.' -Force | Select-Object TaskName,State

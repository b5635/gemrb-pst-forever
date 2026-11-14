# Combat AI dump: analyzes every PST script in the running game (start it with dev.ps1 first)
# and writes D:\Games\GemRB\dev\combat_profiles.md.
#   tb_analyze.ps1 [-GamePath C:\Program Files (x86)\Black Isle\Torment]
param([string]$GamePath = "C:\Program Files (x86)\Black Isle\Torment")
$src = Get-Content -Raw (Join-Path $PSScriptRoot "tb_profiles.py")
$src = $src.Replace("__GAMEPATH__", $GamePath)
$tmp = Join-Path $env:TEMP "tb_profiles_run.py"
Set-Content -Path $tmp -Value $src -Encoding utf8
& (Join-Path $PSScriptRoot "dev.ps1") pyfile $tmp -Timeout 120

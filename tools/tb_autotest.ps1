# Turn based combat autotest (plan C10): the AI plays the party too ("Turn Based Party AI"),
# fights are staged from saves and run to the end unattended. Prints a summary per case and
# fails (exit 1) on a crash, a fight that never ends, or turns that stall.
#
#   tb_autotest.ps1 [-Cases mortuary,ghouls] [-MaxSeconds 240]
#
# A case: a save index, the creatures to turn hostile (script names or global IDs), and an
# optional spot to jump them to. Add cases for the plan's script tests (0403MAGE, 0704RUN,
# 0700ANAM, 0702GARD, 0504ALEK) once there are saves near them.
param(
	[string[]]$Cases = @("mortuary", "ghouls"),
	[int]$MaxSeconds = 240,
	[string]$GameDir = "D:\Games\GemRB"
)
$ErrorActionPreference = "Stop"
$dev = Join-Path $PSScriptRoot "dev.ps1"
$log = Join-Path $GameDir "gemrb.log"

$AllCases = @{
	# one ghoul next to the party at the Mortuary save
	"mortuary" = @{ Save = 2; Hostile = @('"1700ghoul2"'); Jump = @() }
	# a fight-then-flee ghoul jumped next to the party
	"ghouls" = @{ Save = 2; Hostile = @(10068); Jump = @(@(10068, "[420.640]")) }
}

function Py([string]$code) { & $dev py $code }

$failed = $false
foreach ($name in $Cases) {
	$case = $AllCases[$name]
	if (-not $case) { Write-Output "unknown case $name"; $failed = $true; continue }
	Write-Output "=== $name ==="
	& $dev start -Save $case.Save | Out-Null
	Start-Sleep -Seconds 18
	Py "import GemRB; GemRB.SetVar('Turn Based Party AI', 1); print('party ai on')" | Out-Null
	$logStart = (Get-Content $log).Count
	foreach ($j in $case.Jump) { Py "import GemRB; GemRB.ExecuteString('JumpToPoint($($j[1]))', $($j[0]))" | Out-Null }
	foreach ($h in $case.Hostile) {
		if ($h -is [int]) { Py "import GemRB; GemRB.ExecuteString('Enemy()', $h)" | Out-Null }
		else { Py "act('ActionOverride($($h.Replace('"', '`"')),Enemy())')" | Out-Null }
	}

	# wait for the fight to start, then for it to end
	$started = $false
	$ended = $false
	$t0 = Get-Date
	while (((Get-Date) - $t0).TotalSeconds -lt $MaxSeconds) {
		Start-Sleep -Seconds 2
		$state = Py "import GemRB; o=GemRB.GetTurnOrder(); print('none' if o is None else 'round %d' % o['Round'])"
		if (-not (Get-Process -Name gemrb -ErrorAction SilentlyContinue)) { break }
		if ($state -match "round") { $started = $true }
		elseif ($started -and $state -match "none") { $ended = $true; break }
	}

	$lines = (Get-Content $log)[$logStart..((Get-Content $log).Count - 1)]
	$crashed = -not (Get-Process -Name gemrb -ErrorAction SilentlyContinue)
	$rounds = ($lines | Select-String "Turn based combat ends after (\d+) rounds" | ForEach-Object { $_.Matches[0].Groups[1].Value }) -join ","
	$swings = ($lines | Select-String "\[(Hit|Missed|Critical Hit|Critical Miss)\]").Count
	$turns = ($lines | Select-String "CombatDirector/COMBAT\]: Round \d+: ").Count
	$stalls = ($lines | Select-String "doesn't progress").Count
	$deaths = ($lines | Select-String "Stance overridden by death|Turn based combat ends").Count
	Write-Output ("started={0} ended={1} crashed={2} rounds={3} turns={4} swings={5} stalls={6}" -f $started, $ended, $crashed, $rounds, $turns, $swings, $stalls)
	if ($crashed) { & $dev crash }
	if ($crashed -or -not $started -or -not $ended -or $stalls -gt 0) {
		$failed = $true
		$lines | Select-String "CombatDirector" | Select-Object -Last 25 | ForEach-Object { $_.Line }
	}
}
& $dev stop | Out-Null
if ($failed) { Write-Output "AUTOTEST FAILED"; exit 1 }
Write-Output "AUTOTEST PASSED"

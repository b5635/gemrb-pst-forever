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
	"mortuary" = @{ Save = 3; Hostile = @('"1700ghoul2"'); Jump = @() }
	# a fight-then-flee ghoul jumped next to the party
	"ghouls" = @{ Save = 3; Hostile = @(10068); Jump = @(@(10068, "[420.640]")) }
	# the mortuary ghoul against a full party of 8 (MaxPartySize=8: the Nameless One + all seven)
	"party8" = @{ Save = 3; Hostile = @('"1700ghoul2"'); Jump = @(); FullParty = $true }
}

# spawns the companions the save's party lacks next to the Nameless One, then joins them
# (a second pass: the spawns need a moment before ActionOverride can find them)
$SpawnMissing = @'
import GemRB
names = [GemRB.GetPlayerName(i, 1) for i in range(1, GemRB.GetPartySize() + 1)]
for cre, name in (("morte", "Morte"), ("dakkon", "Dak'kon"), ("annah", "Annah"), ("grace", "Fall-from-Grace"), ("nordom", "Nordom"), ("ignus", "Ignus"), ("vhail", "Vhailor")):
	if name not in names:
		act('CreateCreatureAtFeet("%s",0)' % cre)
'@
$JoinAll = @'
import GemRB
for cre in ("morte", "dakkon", "annah", "grace", "nordom", "ignus", "vhail"):
	act('ActionOverride("%s",JoinParty())' % cre)
'@

function Py([string]$code) { & $dev py $code }

$failed = $false
foreach ($name in $Cases) {
	$case = $AllCases[$name]
	if (-not $case) { Write-Output "unknown case $name"; $failed = $true; continue }
	Write-Output "=== $name ==="
	& $dev start -Save $case.Save | Out-Null
	Start-Sleep -Seconds 18
	& $dev key Escape | Out-Null
	Start-Sleep -Seconds 1
	Py "import GemRB; GemRB.SetVar('Turn Based Party AI', 1); print('party ai on')" | Out-Null
	$logStart = (Get-Content $log).Count
	if ($case.FullParty) {
		$tmp = Join-Path $env:TEMP "tb_party.py"
		Set-Content -Encoding utf8 $tmp $SpawnMissing
		& $dev pyfile $tmp | Out-Null
		Start-Sleep -Seconds 2
		Set-Content -Encoding utf8 $tmp $JoinAll
		& $dev pyfile $tmp | Out-Null
		Start-Sleep -Seconds 3
		$size = [int]((Py "import GemRB; print(GemRB.GetPartySize())") -join "").Trim()
		Write-Output "party size $size"
		if ($size -ne 8) { Write-Output "FAILED: party of 8 not assembled"; $failed = $true; continue }
	}
	foreach ($j in $case.Jump) {
		# Crypt NPCs can chew the jump target during the load wait; stand it back up.
		Py "import GemRB; gid=$($j[0]); hp=GemRB.GetPlayerStat(gid,0); st=GemRB.GetPlayerStat(gid,206); hp>=1 or (GemRB.SetPlayerStat(gid,206,st & ~0x800) or GemRB.SetPlayerStat(gid,0,40) or True); GemRB.ExecuteString('JumpToPoint($($j[1]))', gid); print('jump', gid, hp, GemRB.GetPlayerStat(gid,0))" | Out-Null
	}
	foreach ($h in $case.Hostile) {
		if ($h -is [int]) { Py "import GemRB; GemRB.ExecuteString('Enemy()', $h); print('hostile $h')" | Out-Null }
		else { Py "act('ActionOverride($($h.Replace('"', '`"')),Enemy())')" | Out-Null }
	}

	# wait for the fight to start, then for it to end.
	# A one-turn fight can finish inside the 2s poll gap, so sample once immediately
	# and treat a "Turn based combat ends" log line as started+ended.
	$started = $false
	$ended = $false
	$t0 = Get-Date
	$state = Py "import GemRB; o=GemRB.GetTurnOrder(); print('none' if o is None else 'round %d' % o['Round'])"
	if ($state -match "round") { $started = $true }
	while (((Get-Date) - $t0).TotalSeconds -lt $MaxSeconds) {
		if ($started -and $state -match "none") { $ended = $true; break }
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
	if (-not $started -and $rounds) { $started = $true; $ended = $true }
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

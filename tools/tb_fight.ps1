# Stages a turn based fight for testing: loads the Mortuary save, makes the ghoul next to the
# party hostile, then lets the AI and the party (auto attack) play a few rounds and prints the
# director's log.
#   tb_fight.ps1 [-Save 2] [-Ghoul 1700ghoul2] [-Turns 8]
param(
	[int]$Save = 3,
	[string]$Ghoul = "1700ghoul2",
	[int]$Turns = 8,
	[string]$GameDir = "C:\Games\GemRB"
)
$dev = Join-Path $PSScriptRoot "dev.ps1"
& $dev start -Save $Save | Out-Null
Start-Sleep -Seconds 18
& $dev py "act('ActionOverride(`"$Ghoul`",Enemy())'); print(here())"
Start-Sleep -Seconds 4

# party turns: attack the ghoul, then end the turn once it's done
$py = @"
import GemRB
o = GemRB.GetTurnOrder()
b = GemRB.GetTurnBudget()
tried = globals().setdefault('tbTried', set())
if o and b:
	key = (o['Round'], b['ID'])
	if not b['MainActionUsed'] and not b['Busy'] and key not in tried:
		tried.add(key)
		GemRB.ExecuteString('Attack("$Ghoul")', b['ID'])
		print('attack', b['ID'])
	elif not b['Busy']:
		GemRB.EndTurn()
		print('end', b['ID'])
print(o and o['Round'], o and o['Active'])
"@
$tmp = Join-Path $env:TEMP "tb_turn.py"
Set-Content -Path $tmp -Value $py -Encoding utf8
for ($i = 0; $i -lt $Turns; $i++) {
	& $dev pyfile $tmp
	Start-Sleep -Seconds 3
	if ($i -eq 1) { & $dev shot (Join-Path $PSScriptRoot "..\shots\tb_fight.png") | Out-Null }
}
Select-String -Path (Join-Path $GameDir "gemrb.log") -Pattern "CombatDirector|\[Hit|\[Miss|\[Crit" | Select-Object -Last 45 | ForEach-Object { $_.Line }

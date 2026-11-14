# Turn based test: spells and fleeing. Moves the party next to a fight-then-flee ghoul
# (1700GUL7, flees below 50% HP) in the Mortuary, makes it hostile, then Dak'kon casts at it
# and the others attack. Prints the director log.
#   tb_flee_cast.ps1 [-Save 2] [-Target 10068] [-Spell 2119 (spell.ids number)] [-Turns 24]
param(
	[int]$Save = 2,
	[int]$Target = 10068,
	[int]$Spell = 2119,
	[int]$Turns = 24,
	[string]$GameDir = "D:\Games\GemRB"
)
$dev = Join-Path $PSScriptRoot "dev.ps1"
& $dev start -Save $Save | Out-Null
Start-Sleep -Seconds 18
& $dev py "import GemRB; GemRB.ExecuteString('JumpToPoint([420.640])', $Target); print('moved')"
Start-Sleep -Seconds 6
& $dev py "import GemRB; GemRB.ExecuteString('Enemy()', $Target); print('hostile')"
Start-Sleep -Seconds 4

$py = @"
import GemRB
o = GemRB.GetTurnOrder()
b = GemRB.GetTurnBudget()
tried = globals().setdefault('tbTried', set())
if o and b:
	key = (o['Round'], b['ID'])
	if not b['MainActionUsed'] and not b['Busy'] and key not in tried:
		tried.add(key)
		if b['ID'] == 10004 and b['CanCast'] and $Spell > 0:
			GemRB.ExecuteActionAt(b['ID'], 'ForceSpell([-1],$Spell)', $Target)
			print('cast', b['ID'])
		else:
			GemRB.ExecuteActionAt(b['ID'], 'Attack([-1])', $Target)
			print('attack', b['ID'])
	elif not b['Busy']:
		GemRB.EndTurn()
		print('end', b['ID'])
print(o and o['Round'], o and o['Active'])
"@
$tmp = Join-Path $env:TEMP "tb_turn2.py"
Set-Content -Path $tmp -Value $py -Encoding utf8
for ($i = 0; $i -lt $Turns; $i++) {
	& $dev pyfile $tmp | Out-Null
	Start-Sleep -Seconds 3
}
& $dev shot (Join-Path $PSScriptRoot "..\shots\tb_flee.png") | Out-Null
$L = Get-Content (Join-Path $GameDir "gemrb.log")
$s = ($L | Select-String "Turn based combat starts" | Select-Object -First 1).LineNumber
if ($s) { $L[($s - 1)..($L.Count - 1)] | Select-String "CombatDirector|\[Hit|\[Miss|\[Crit|Spell|Cast" | Select-Object -First 90 | ForEach-Object { $_.Line } }

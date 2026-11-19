# Spell lab driver: ends party turns (no action) until -Until's turn comes up, or for -Turns turns.
#   tb_lab_step.ps1 -Until 10004        tb_lab_step.ps1 -Turns 3
param([int]$Until = 0, [int]$Turns = 0, [int]$Max = 40)
$dev = Join-Path $PSScriptRoot "dev.ps1"
$ended = 0
for ($i = 0; $i -lt $Max; $i++) {
	$o = & $dev py "o=GemRB.GetTurnOrder(); b=GemRB.GetTurnBudget(); print(o and o['Active'], bool(b and b['Busy']), o and o['Round'])"
	$parts = ("$o".Trim()) -split "\s+"
	if ($parts[0] -eq "None") { Write-Output "no fight"; break }
	$active = [int]$parts[0]
	if ($Until -and $active -eq $Until -and $parts[1] -eq "False") { Write-Output "turn of $active, round $($parts[2])"; break }
	if ($Turns -and $ended -ge $Turns) { Write-Output "now $active, round $($parts[2])"; break }
	$party = & $dev py "print(GemRB.GetTurnOrder()['Active'] in [c['ID'] for c in GemRB.GetTurnOrder()['Combatants'] if c['IsPC']])"
	if ("$party".Trim() -eq "True" -and $parts[1] -eq "False") {
		& $dev py "GemRB.EndTurn()" | Out-Null
		$ended++
	}
	Start-Sleep -Milliseconds 1500
}

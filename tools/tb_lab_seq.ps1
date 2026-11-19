# Spell lab: runs a cast sequence. Each entry "caster:spell:target" waits for the caster's turn,
# casts, waits until the turn is no longer busy (max 20 s) and prints targets' HP, the world
# clock and the timer's fade/shake state. Targets are spell-lab variables or global IDs.
#   tb_lab_seq.ps1 -Seq "10004:2502:t[1]","10002:2307:10101" -Watch "t"
param([string[]]$Seq, [string]$Watch = "t")
$dev = Join-Path $PSScriptRoot "dev.ps1"
$step = Join-Path $PSScriptRoot "tb_lab_step.ps1"
foreach ($entry in $Seq) {
	$caster, $spell, $target = $entry -split ":"
	$r = & $step -Until $caster
	Write-Output "== $entry ($r)"
	& $dev py "cast($caster, $spell, $target)" | Out-Null
	for ($i = 0; $i -lt 20; $i++) {
		Start-Sleep 1
		$s = & $dev py "o=GemRB.GetTurnOrder(); b=GemRB.GetTurnBudget(); d=GemRB.DebugEffects($caster); print(bool(b and b['Busy']), d['GameTime'], d['Fading'], d['Shake'], [snap(x)['HP'] for x in $Watch])"
		if ($i % 3 -eq 0 -or "$s" -match "^False") { Write-Output "  t+$($i+1)s busy/time/fading/shake/HP: $("$s".Trim())" }
		if ("$s" -match "^False") { break }
	}
	& $dev py "GemRB.EndTurn()" | Out-Null
}

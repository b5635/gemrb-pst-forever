# Turn based movement accuracy: stages the Mortuary ghoul fight and has party members make
# random click-and-confirm moves, checking each walk ends exactly where the preview line said.
#   tb_move_accuracy.ps1 [-Save 2] [-Ghoul 1700ghoul2] [-Polls 120]
param(
	[int]$Save = 3,
	[string]$Ghoul = "1700ghoul2",
	[int]$Polls = 120
)
$dev = Join-Path $PSScriptRoot "dev.ps1"
$py = Join-Path $PSScriptRoot "tb_move_accuracy.py"
& $dev start -Save $Save | Out-Null
Start-Sleep -Seconds 18
& $dev py "act('ActionOverride(`"$Ghoul`",Enemy())'); print(here())"
Start-Sleep -Seconds 4
$last = ""
for ($i = 0; $i -lt $Polls; $i++) {
	$out = & $dev pyfile $py
	if ($out -match "^(timeout|game exited)") { $out; exit 1 }
	$last = $out
	Start-Sleep -Milliseconds 700
}
$last
$m = [regex]::Match(($last -join "`n"), "bad=(\d+)")
if ($m.Success -and [int]$m.Groups[1].Value -gt 0) { exit 1 }

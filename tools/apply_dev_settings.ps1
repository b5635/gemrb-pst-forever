# Forces the settings from tools\dev_settings.ini into the installed game (see that file).
# Usage: powershell -File tools\apply_dev_settings.ps1 [-GameDir D:\Games\GemRB]
param(
	[string]$GameDir = "D:\Games\GemRB",
	[string]$Settings = (Join-Path $PSScriptRoot "dev_settings.ini")
)
$ErrorActionPreference = "Stop"

# file -> section ("" for GemRB.cfg) -> ordered list of [key, value]
$groups = [ordered]@{}
$current = $null
foreach ($raw in Get-Content $Settings) {
	$line = $raw.Trim()
	if ($line -eq "" -or $line.StartsWith(";")) { continue }
	if ($line -match '^\[(.+)\]$') {
		$current = $Matches[1]
		if (-not $groups.Contains($current)) { $groups[$current] = New-Object System.Collections.ArrayList }
		continue
	}
	$k, $v = $line -split '=', 2
	[void]$groups[$current].Add(@($k.Trim(), $v.Trim()))
}

function Set-Lines([System.Collections.ArrayList]$lines, [int]$start, [int]$end, [string]$key, [string]$text) {
	# replace key in [start, end) or insert at end; returns the new end
	$pattern = '^\s*' + [regex]::Escape($key) + '\s*='
	for ($i = $start; $i -lt $end; $i++) {
		if ($lines[$i] -match $pattern) { $lines[$i] = $text; return $end }
	}
	$lines.Insert($end, $text)
	return $end + 1
}

foreach ($group in $groups.Keys) {
	$entries = $groups[$group]
	if ($group -eq "GemRB.cfg") {
		$file = Join-Path $GameDir "GemRB.cfg"
		$lines = New-Object System.Collections.ArrayList
		if (Test-Path $file) { $lines.AddRange([string[]](Get-Content $file)) }
		foreach ($e in $entries) { [void](Set-Lines $lines 0 $lines.Count $e[0] "$($e[0])=$($e[1])") }
	} else {
		$rel, $section = $group -split ':', 2
		$file = Join-Path $GameDir $rel
		$lines = New-Object System.Collections.ArrayList
		if (Test-Path $file) { $lines.AddRange([string[]](Get-Content $file)) }
		$head = -1
		for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -ieq "[$section]") { $head = $i; break } }
		if ($head -lt 0) { [void]$lines.Add("[$section]"); $head = $lines.Count - 1 }
		$end = $head + 1
		while ($end -lt $lines.Count -and -not ($lines[$end].Trim() -match '^\[.+\]$')) { $end++ }
		# insert before trailing blank lines of the section
		while ($end -gt $head + 1 -and $lines[$end - 1].Trim() -eq "") { $end-- }
		foreach ($e in $entries) { $end = Set-Lines $lines ($head + 1) $end $e[0] "$($e[0]) = $($e[1])" }
	}
	$dir = Split-Path $file
	if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
	Set-Content -Path $file -Value ([string[]]$lines) -Encoding ascii
	Write-Host "dev settings: $($entries.Count) keys -> $file"
}

# Drive the installed GemRB for testing (works with the DevConsole.py poller and the GL driver's shot hook).
#
#   dev.ps1 start [-Save 0]          launch the game, auto-loading a save by name (-Save wererat) or by index in
#                                    slot order (0 = Auto-Save, not the newest); -Save -1 = main menu
#   dev.ps1 py "print(here())"       run Python inside the game, print its output (helpers: here, act, goto, pc)
#   dev.ps1 pyfile script.py         same, from a file
#   dev.ps1 click X Y [-Right]       click at game-window client pixel X,Y (posted to the window, no focus needed)
#   dev.ps1 move X Y                 move the mouse there (hover), no click
#   dev.ps1 key NAME                 send a key (virtual-key name from System.Windows.Forms.Keys, e.g. Escape, Space, A)
#   dev.ps1 shot [out.png]           screenshot of the current frame (default shots\dev.png)
#   dev.ps1 status                   running?  plus last log lines
#   dev.ps1 log [-Lines 60]          tail gemrb.log
#   dev.ps1 crash                    show crashes\last_crash.txt
#   dev.ps1 stop                     close the game
param(
	[Parameter(Position = 0)][string]$Cmd = "status",
	[Parameter(Position = 1)][string]$Arg1 = "",
	[Parameter(Position = 2)][string]$Arg2 = "",
	[string]$Save = "0",
	[int]$Lines = 40,
	[int]$Timeout = 15,
	[switch]$Right,
	[string]$GameDir = "D:\Games\GemRB"
)
$ErrorActionPreference = "Stop"
$devDir = Join-Path $GameDir "dev"
$pidFile = Join-Path $devDir "pid"
New-Item -ItemType Directory -Force $devDir | Out-Null

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DevW32 {
	[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
"@

function Get-Game {
	if (Test-Path $pidFile) {
		$id = [int](Get-Content $pidFile)
		$p = Get-Process -Id $id -ErrorAction SilentlyContinue
		if ($p -and $p.ProcessName -eq "gemrb") { return $p }
	}
	return Get-Process gemrb -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Need-Game {
	$p = Get-Game
	if (-not $p) {
		Write-Output "game is not running"
		Show-Crash -OnlyNew
		exit 1
	}
	return $p
}

function Show-Crash([switch]$OnlyNew) {
	$c = Join-Path $GameDir "crashes\last_crash.txt"
	if (-not (Test-Path $c)) { if (-not $OnlyNew) { Write-Output "no crash report" }; return }
	$started = if (Test-Path $pidFile) { (Get-Item $pidFile).LastWriteTime } else { [DateTime]::MinValue }
	if ($OnlyNew -and (Get-Item $c).LastWriteTime -lt $started) { return }
	Get-Content $c
}

function Lparam([int]$x, [int]$y) { return [IntPtr](($y -shl 16) -bor ($x -band 0xffff)) }

switch ($Cmd) {
	"start" {
		$old = Get-Game
		if ($old) { Stop-Process -Id $old.Id -Force; Start-Sleep -Milliseconds 500 }
		if ($Save -ne "-1") { $env:GEMRB_AUTOLOAD = "$Save" } else { Remove-Item Env:GEMRB_AUTOLOAD -ErrorAction SilentlyContinue }
		$p = Start-Process -FilePath (Join-Path $GameDir "gemrb.exe") -WorkingDirectory $GameDir -PassThru -WindowStyle Normal
		Set-Content $pidFile $p.Id
		Write-Output "started pid $($p.Id)"
	}
	{ $_ -in "py", "pyfile" } {
		$p = Need-Game
		$src = if ($Cmd -eq "pyfile") { Get-Content -Raw $Arg1 } else { $Arg1 }
		$out = Join-Path $devDir "out.txt"
		if (Test-Path $out) { Remove-Item $out }
		$tmp = Join-Path $devDir "cmd.tmp"
		[System.IO.File]::WriteAllText($tmp, $src)
		Move-Item -Force $tmp (Join-Path $devDir "cmd.py")
		$deadline = (Get-Date).AddSeconds($Timeout)
		while (-not (Test-Path $out)) {
			if ((Get-Date) -gt $deadline) { Write-Output "timeout: no reply (game paused in a modal, or still loading?)"; exit 1 }
			if ($p.HasExited) { Write-Output "game exited"; Show-Crash -OnlyNew; exit 1 }
			Start-Sleep -Milliseconds 100
		}
		Get-Content $out | Where-Object { $_ -notmatch '^#done' }
	}
	"click" {
		$p = Need-Game
		$h = $p.MainWindowHandle
		$l = Lparam ([int]$Arg1) ([int]$Arg2)
		[DevW32]::PostMessage($h, 0x0200, [IntPtr]0, $l) | Out-Null # WM_MOUSEMOVE
		Start-Sleep -Milliseconds 80
		if ($Right) { $down = 0x0204; $up = 0x0205; $mk = 2 } else { $down = 0x0201; $up = 0x0202; $mk = 1 }
		[DevW32]::PostMessage($h, $down, [IntPtr]$mk, $l) | Out-Null
		Start-Sleep -Milliseconds 60
		[DevW32]::PostMessage($h, $up, [IntPtr]0, $l) | Out-Null
		Write-Output "clicked $Arg1,$Arg2"
	}
	"move" {
		$p = Need-Game
		[DevW32]::PostMessage($p.MainWindowHandle, 0x0200, [IntPtr]0, (Lparam ([int]$Arg1) ([int]$Arg2))) | Out-Null # WM_MOUSEMOVE
		Write-Output "moved to $Arg1,$Arg2"
	}
	"key" {
		$p = Need-Game
		Add-Type -AssemblyName System.Windows.Forms
		$vk = [int][System.Windows.Forms.Keys]$Arg1
		[DevW32]::PostMessage($p.MainWindowHandle, 0x0100, [IntPtr]$vk, [IntPtr]1) | Out-Null # WM_KEYDOWN
		Start-Sleep -Milliseconds 60
		[DevW32]::PostMessage($p.MainWindowHandle, 0x0101, [IntPtr]$vk, [IntPtr]0xC0000001) | Out-Null
		Write-Output "key $Arg1"
	}
	"shot" {
		$p = Need-Game
		$outPng = if ($Arg1) { $Arg1 } else { "shots\dev.png" }
		$outPng = [System.IO.Path]::GetFullPath($outPng)
		$bmp = [System.IO.Path]::ChangeExtension($outPng, ".bmp")
		if (Test-Path $bmp) { Remove-Item $bmp }
		New-Item -ItemType Directory -Force (Split-Path $outPng) | Out-Null
		Set-Content -Encoding ascii (Join-Path $devDir "shot.req") $bmp
		$deadline = (Get-Date).AddSeconds($Timeout)
		while (-not (Test-Path $bmp)) {
			if ((Get-Date) -gt $deadline) { Write-Output "timeout: no frame (needs VideoDriver=opengl)"; exit 1 }
			Start-Sleep -Milliseconds 100
		}
		Add-Type -AssemblyName System.Drawing
		$img = [System.Drawing.Image]::FromFile($bmp)
		$img.Save($outPng, [System.Drawing.Imaging.ImageFormat]::Png)
		$img.Dispose(); Remove-Item $bmp
		Write-Output "saved $outPng"
	}
	"status" {
		$p = Get-Game
		if ($p) { Write-Output "running pid $($p.Id)" } else { Write-Output "not running"; Show-Crash -OnlyNew }
		$log = Join-Path $GameDir "gemrb.log"
		if (Test-Path $log) { Get-Content $log -Tail 10 }
	}
	"log" { Get-Content (Join-Path $GameDir "gemrb.log") -Tail $Lines }
	"crash" { Show-Crash }
	"stop" {
		$p = Get-Game
		if ($p) { Stop-Process -Id $p.Id -Force; Write-Output "stopped" } else { Write-Output "not running" }
	}
	default { Get-Content $MyInvocation.MyCommand.Path | Select-Object -Skip 1 -First 12 }
}

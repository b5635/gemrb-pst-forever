# Launches the installed GemRB with a save auto-loaded, waits, captures the game window to a PNG, then closes it.
# Usage: powershell -File tools\pst_shot.ps1 -Out shots\baseline.png [-Save 0] [-Wait 25] [-GameDir D:\Games\GemRB]
param(
	[string]$Out = "shots\shot.png",
	[int]$Save = 0,
	[int]$Wait = 25,
	[string]$GameDir = "D:\Games\GemRB",
	[string]$Driver = "",
	[string[]]$Set = @(),
	[switch]$Keep
)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
	[StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
	[DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
	[DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
	[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
	[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
	[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
	[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
[W32]::SetProcessDPIAware() | Out-Null

$env:GEMRB_AUTOLOAD = "$Save"
# optional overrides go into a temporary copy of the config (VideoDriver and any Key=Value from -Set)
$gemArgs = @()
if ($Driver -or $Set.Count) {
	$cfg = Get-Content (Join-Path $GameDir "GemRB.cfg") | Where-Object { $_ -notmatch '^\s*VideoDriver\s*=' }
	$keys = $Set | ForEach-Object { ($_ -split '=')[0] }
	$cfg = $cfg | Where-Object { $line = $_; -not ($keys | Where-Object { $line -match "^\s*$_\s*=" }) }
	if ($Driver) { $cfg += "VideoDriver=$Driver" }
	$cfg += $Set
	$tmpCfg = Join-Path $GameDir "GemRB.shot.cfg"
	$cfg | Set-Content -Encoding ascii $tmpCfg
	$gemArgs = @("-c", $tmpCfg)
}
# the GL driver can write its own frame (no window focus needed)
$useDevShot = ($Driver -ne "sdl") -and ((Get-Content (Join-Path $GameDir "GemRB.cfg") | Select-String -Quiet '^\s*VideoDriver\s*=\s*opengl') -or $Driver -eq "opengl")
if ($useDevShot) {
	$bmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetFullPath($Out), ".bmp")
	if (Test-Path $bmp) { Remove-Item $bmp }
	$env:GEMRB_GL_SHOT = "$bmp;$Wait"
}
if ($gemArgs.Count) {
	$p = Start-Process -FilePath (Join-Path $GameDir "gemrb.exe") -WorkingDirectory $GameDir -ArgumentList $gemArgs -PassThru
} else {
	$p = Start-Process -FilePath (Join-Path $GameDir "gemrb.exe") -WorkingDirectory $GameDir -PassThru
}
Start-Sleep -Seconds $Wait
if ($useDevShot) {
	for ($i = 0; $i -lt 30 -and -not (Test-Path $bmp); $i++) { Start-Sleep -Milliseconds 500 }
	Start-Sleep -Milliseconds 500
	if (Test-Path $bmp) {
		$img = [System.Drawing.Image]::FromFile($bmp)
		$img.Save([System.IO.Path]::GetFullPath($Out), [System.Drawing.Imaging.ImageFormat]::Png)
		$img.Dispose(); Remove-Item $bmp
		Write-Output "saved $Out (driver capture)"
		if (-not $Keep) { Stop-Process -Id $p.Id -Force }
		exit 0
	}
	Write-Output "driver capture missing, falling back to desktop grab"
}
$p.Refresh()
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { Write-Error "no window"; exit 1 }
[W32]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 500
$r = New-Object W32+RECT
[W32]::GetClientRect($h, [ref]$r) | Out-Null
$pt = New-Object W32+POINT
[W32]::ClientToScreen($h, [ref]$pt) | Out-Null
$w = $r.R - $r.L; $ht = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($pt.X, $pt.Y, 0, 0, (New-Object System.Drawing.Size $w, $ht))
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out (${w}x${ht})"
if (-not $Keep) { Stop-Process -Id $p.Id -Force }

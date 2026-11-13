# Crops (and optionally scales) a region out of an image: crop.ps1 in.png out.png x y w h [scale]
param([string]$In, [string]$OutFile, [int]$X, [int]$Y, [int]$W, [int]$H, [double]$Scale = 1.0)
Add-Type -AssemblyName System.Drawing
$s = [System.Drawing.Image]::FromFile([System.IO.Path]::GetFullPath($In))
$ow = [int]($W * $Scale); $oh = [int]($H * $Scale)
$b = New-Object System.Drawing.Bitmap $ow, $oh
$g = [System.Drawing.Graphics]::FromImage($b)
$g.InterpolationMode = 'NearestNeighbor'
$g.PixelOffsetMode = 'Half'
$g.DrawImage($s, (New-Object System.Drawing.Rectangle 0, 0, $ow, $oh), (New-Object System.Drawing.Rectangle $X, $Y, $W, $H), [System.Drawing.GraphicsUnit]::Pixel)
$b.Save([System.IO.Path]::GetFullPath($OutFile), [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose(); $s.Dispose()

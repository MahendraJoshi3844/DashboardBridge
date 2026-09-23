param([string]$Title = "t2pbi", [string]$Out = "window.png")

# PrintWindow with PW_RENDERFULLCONTENT reads the window's own pixels, so it
# works whether or not the window is in front. CopyFromScreen does not: it
# captures whatever is physically on screen at those coordinates.
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$proc = Get-Process | Where-Object { $_.MainWindowTitle -eq $Title } | Select-Object -First 1
if (-not $proc) { Write-Error "No window titled '$Title'"; exit 1 }
$h = $proc.MainWindowHandle

$r = New-Object Win+RECT
[void][Win]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left; $hgt = $r.Bottom - $r.Top
if ($w -le 0 -or $hgt -le 0) { Write-Error "Window has no size"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
$ok = [Win]::PrintWindow($h, $dc, 2)   # 2 = PW_RENDERFULLCONTENT
$g.ReleaseHdc($dc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
if (-not $ok) { Write-Warning "PrintWindow returned false" }
Write-Output "saved $Out ($w x $hgt)"

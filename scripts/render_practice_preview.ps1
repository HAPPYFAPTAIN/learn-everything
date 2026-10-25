param([string]$Output = 'output/_shots/practice-window.png')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
$root = Split-Path $PSScriptRoot -Parent
$source = [IO.File]::ReadAllText((Join-Path $root 'learning_ext/agent/practice_window.ps1'))
$xaml = [regex]::Match($source, '(?s)<Window xmlns=.*?</Window>').Value
$window = [Windows.Markup.XamlReader]::Parse($xaml)
$visual = $window.Content
$size = [Windows.Size]::new($window.Width, $window.Height)
$visual.Measure($size)
$visual.Arrange([Windows.Rect]::new($size))
$visual.UpdateLayout()
$bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new([int]$size.Width,[int]$size.Height,96,96,[Windows.Media.PixelFormats]::Pbgra32)
$bitmap.Render($visual)
$encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
$path = Join-Path $root $Output
[IO.Directory]::CreateDirectory((Split-Path $path -Parent)) | Out-Null
$stream = [IO.File]::Create($path)
try { $encoder.Save($stream) } finally { $stream.Dispose() }
$path

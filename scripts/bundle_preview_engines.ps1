param(
    [string]$LibreOfficeSource = 'C:\Program Files\LibreOffice',
    [string]$SumatraSource = "$env:LOCALAPPDATA\SumatraPDF"
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$destination = Join-Path $projectRoot 'vendor\preview'
if (!(Test-Path -LiteralPath (Join-Path $LibreOfficeSource 'program\soffice.com'))) { throw 'LibreOffice source is missing' }
if (!(Test-Path -LiteralPath (Join-Path $SumatraSource 'sumatrapdf-tool.exe'))) { throw 'SumatraPDF command-line renderer is missing' }
New-Item -ItemType Directory -Force -Path "$destination\libreoffice", "$destination\sumatra" | Out-Null
foreach ($item in @('program', 'share', 'presets', 'readmes', 'LICENSE.html', 'license.txt', 'NOTICE', 'CREDITS.fodt')) {
    Copy-Item -LiteralPath (Join-Path $LibreOfficeSource $item) -Destination "$destination\libreoffice" -Recurse -Force
}
foreach ($item in @('sumatrapdf-tool.exe', 'libmupdf.dll')) {
    Copy-Item -LiteralPath (Join-Path $SumatraSource $item) -Destination "$destination\sumatra" -Force
}
if (!(Test-Path -LiteralPath "$destination\sumatra\COPYING")) {
    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/sumatrapdfreader/sumatrapdf/master/COPYING' -OutFile "$destination\sumatra\COPYING"
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\PREVIEW_COMPONENTS.md') -Destination "$destination\PREVIEW_COMPONENTS.md" -Force
Write-Output 'Bundled LibreOffice and SumatraPDF renderers. No personal profiles or credentials were copied.'

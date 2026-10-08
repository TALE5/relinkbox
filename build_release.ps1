# Build the two Windows packages people can download:
#   release\Relinkbox.exe  — one file
#   release\Relinkbox.zip  — unzip, then run Relinkbox.exe inside the folder
$ErrorActionPreference = "Stop"
# PyInstaller writes warnings to stderr. Do not treat that as a failed command.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Create the venv first. See README.md, Develop from source."
}

& $python -m pip install "pyinstaller>=6.16"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$release = Join-Path $PSScriptRoot "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null

function Build-Relinkbox {
    param([ValidateSet("onedir", "onefile")][string]$Mode)
    if ($Mode -eq "onefile") {
        $env:RELINKBOX_ONEFILE = "1"
        $dist = "dist\onefile"
        $work = "build\onefile"
    } else {
        Remove-Item Env:RELINKBOX_ONEFILE -ErrorAction SilentlyContinue
        $dist = "dist\onedir"
        $work = "build\onedir"
    }
    & $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work ".\relinkbox.spec"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function New-RelinkboxZip {
    param([string]$SourceDir, [string]$Destination)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # Zip the folder itself so unpacking creates Relinkbox\Relinkbox.exe.
    $parent = Split-Path $SourceDir -Parent
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            if (Test-Path $Destination) { Remove-Item $Destination -Force }
            [System.IO.Compression.ZipFile]::CreateFromDirectory($parent, $Destination)
            return
        } catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host "Building folder package..."
Build-Relinkbox -Mode onedir

$zip = Join-Path $release "Relinkbox.zip"
New-RelinkboxZip -SourceDir (Join-Path $PSScriptRoot "dist\onedir\Relinkbox") -Destination $zip

Write-Host "Building single exe..."
Build-Relinkbox -Mode onefile
Copy-Item "dist\onefile\Relinkbox.exe" (Join-Path $release "Relinkbox.exe") -Force

Write-Host ""
Write-Host "Done."
Write-Host "  release\Relinkbox.exe"
Write-Host "  release\Relinkbox.zip"

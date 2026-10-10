# Build the two Windows packages people can download:
#   release\Relinkbox.exe  — one file
#   release\Relinkbox.zip  — unzip, then run Relinkbox.exe inside the folder
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# pip and PyInstaller log normal progress to stderr. Windows PowerShell 5.1 turns that into
# errors when output is redirected, so judge native commands by their exit code only.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        Write-Host "Command failed with exit code ${code}: $Exe $($Arguments -join ' ')" -ForegroundColor Red
        exit $code
    }
}

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Create the venv first. See README.md, Develop from source."
}

Invoke-Native $python @("-m", "pip", "install", "pyinstaller>=6.16")

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
    Invoke-Native $python @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", $dist, "--workpath", $work, ".\relinkbox.spec")
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

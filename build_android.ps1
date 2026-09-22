param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Host 'WSL is not installed or not available on this system.' -ForegroundColor Red
    Write-Host 'Install WSL2 + Ubuntu first, then run this script again.' -ForegroundColor Yellow
    Write-Host 'Suggested command:' -ForegroundColor Cyan
    Write-Host '  wsl.exe --install' -ForegroundColor Gray
    exit 1
}

$wslRoots = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss',
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss'
)

$wslDistroCount = 0
foreach ($root in $wslRoots) {
    if (Test-Path $root) {
        $wslDistroCount += (Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue | Measure-Object).Count
    }
}

if ($wslDistroCount -lt 1) {
    Write-Host 'WSL support does not appear to be installed yet.' -ForegroundColor Red
    Write-Host 'Install WSL2 + Ubuntu first, then run this script again.' -ForegroundColor Yellow
    Write-Host 'Suggested command:' -ForegroundColor Cyan
    Write-Host '  wsl.exe --install' -ForegroundColor Gray
    exit 1
}

$drive = $ProjectRoot.Substring(0, 1).ToLowerInvariant()
$pathPart = $ProjectRoot.Substring(2) -replace '\\', '/'
$wslProjectRoot = "/mnt/$drive$pathPart"

$cleanCommand = if ($Clean) { 'rm -rf .buildozer bin' } else { 'true' }
$command = @"
set -e
cd '$wslProjectRoot'
chmod +x build_android.sh
$cleanCommand
./build_android.sh
"@

wsl.exe bash -lc $command



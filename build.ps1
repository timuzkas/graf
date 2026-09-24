# builds a windows executable
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean graf.spec

Write-Host "Built: dist\graf.exe"

# Run project in dev mode on Windows
param(
    [switch]$Install
)

# Activate venv if present
if (Test-Path -Path .\venv\Scripts\Activate.ps1) {
    . .\venv\Scripts\Activate.ps1
} else {
    Write-Host "No venv found. Consider creating one: python -m venv venv" -ForegroundColor Yellow
}

if ($Install) {
    Write-Host "Installing dependencies (Windows will install emulator where appropriate)..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
}

Write-Host "Starting application (dev mode)"
python .\start.py

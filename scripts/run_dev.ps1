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

    # Use a narrower requirements file on Windows to avoid hardware packages that fail to build
    if ($env:OS -eq 'Windows_NT' -and (Test-Path "requirements-windows.txt")) {
        Write-Host "Detected Windows: installing Windows-friendly requirements..."
        pip install -r requirements-windows.txt
    }
    else {
        pip install -r requirements.txt
    }

    # Attempt to install one of several optional emulator packages (no-op if already present)
    # Try a short list of common emulator package names; avoid noisy 'package not found' pip errors
    $emulators = @('fake-rpi', 'fake_rpi')
    $installed = $false
    foreach ($pkg in $emulators) {
        Write-Host "Attempting to install emulator package: $pkg"
        & pip install --disable-pip-version-check $pkg > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Installed emulator: $pkg" -ForegroundColor Green
            $installed = $true
            break
        } else {
            Write-Host "Package $pkg not available or failed to install; trying next..." -ForegroundColor Yellow
        }
    }
    if (-not $installed) {
        Write-Host "No emulator package installed. The project includes local stubs (src_service/gpio_stub.py and src_service/pn532_stub.py) that will be used automatically." -ForegroundColor Yellow
        Write-Host "If you want an emulator, consider installing one of: fake-rpi, fake_rpi, or an alternative that provides the RPi.GPIO API." -ForegroundColor Yellow
    }

    # Ensure debugpy is installed in the venv so VS Code debugging works
    try {
        $venvPy = Join-Path $PWD 'venv\Scripts\python.exe'
        if (Test-Path $venvPy) {
            Write-Host "Checking for debugpy in venv..."
            & $venvPy -m pip show debugpy > $null 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Installing debugpy into the venv..."
                & $venvPy -m pip install debugpy
            } else {
                Write-Host "debugpy already present in venv."
            }
        } else {
            Write-Host "No venv python found; skipping debugpy install." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Failed to ensure debugpy: $_" -ForegroundColor Yellow
    }
}

Write-Host "Starting application (dev mode)"
python .\start.py

# Test runner script for Door Controller (PowerShell)
# Usage: .\scripts\run_tests.ps1 [mode]
# Modes: quiet, verbose, coverage, single

param(
    [string]$Mode = "normal",
    [string]$TestModule = ""
)

Write-Host "Door Controller - Test Suite" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment if it exists
if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    & "venv\Scripts\Activate.ps1"
}

# Check Python version
Write-Host "Python version:" -ForegroundColor Green
python --version
Write-Host ""

switch ($Mode.ToLower()) {
    "quiet" {
        Write-Host "Running tests (quiet mode)..." -ForegroundColor Yellow
        python -m unittest discover -s tests -p "test_*.py"
    }
    "verbose" {
        Write-Host "Running tests (verbose mode)..." -ForegroundColor Yellow
        python -m unittest discover -s tests -p "test_*.py" -v
    }
    "coverage" {
        Write-Host "Running tests with coverage..." -ForegroundColor Yellow

        # Check if coverage is installed
        $coverageInstalled = python -m pip list | Select-String "coverage"
        if (-not $coverageInstalled) {
            Write-Host "Installing coverage..." -ForegroundColor Yellow
            python -m pip install coverage
        }

        python -m coverage run -m unittest discover -s tests -p "test_*.py"
        Write-Host ""
        Write-Host "Coverage Report:" -ForegroundColor Green
        python -m coverage report -m
        Write-Host ""
        Write-Host "Generating HTML coverage report..." -ForegroundColor Yellow
        python -m coverage html
        Write-Host "HTML report generated in htmlcov\index.html" -ForegroundColor Green
    }
    "single" {
        if ([string]::IsNullOrEmpty($TestModule)) {
            Write-Host "Error: Test module name required" -ForegroundColor Red
            Write-Host "Usage: .\scripts\run_tests.ps1 single <test_module>" -ForegroundColor Yellow
            Write-Host "Example: .\scripts\run_tests.ps1 single test_config" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "Running single test module: $TestModule" -ForegroundColor Yellow
        python -m unittest "tests.$TestModule" -v
    }
    default {
        Write-Host "Running tests (normal mode)..." -ForegroundColor Yellow
        python -m unittest discover -s tests -p "test_*.py" -v
    }
}

Write-Host ""
Write-Host "Tests completed!" -ForegroundColor Green

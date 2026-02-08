#!/bin/bash
# Test runner script for Door Controller

set -e

echo "Door Controller - Test Suite"
echo "=============================="

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Check Python version
echo "Python version:"
python3 --version
echo ""

# Run tests with different verbosity levels
case "${1:-normal}" in
    quiet)
        echo "Running tests (quiet mode)..."
        python3 -m unittest discover -s tests -p "test_*.py"
        ;;
    verbose)
        echo "Running tests (verbose mode)..."
        python3 -m unittest discover -s tests -p "test_*.py" -v
        ;;
    coverage)
        echo "Running tests with coverage..."
        if ! command -v coverage &> /dev/null; then
            echo "Installing coverage..."
            pip install coverage
        fi
        coverage run -m unittest discover -s tests -p "test_*.py"
        echo ""
        echo "Coverage Report:"
        coverage report -m
        echo ""
        echo "Generating HTML coverage report..."
        coverage html
        echo "HTML report generated in htmlcov/index.html"
        ;;
    single)
        if [ -z "$2" ]; then
            echo "Usage: $0 single <test_module>"
            echo "Example: $0 single test_config"
            exit 1
        fi
        echo "Running single test module: $2"
        python3 -m unittest "tests.$2" -v
        ;;
    *)
        echo "Running tests (normal mode)..."
        python3 -m unittest discover -s tests -p "test_*.py" -v
        ;;
esac

echo ""
echo "Tests completed!"

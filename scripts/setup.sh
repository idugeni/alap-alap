#!/bin/bash

# Alap-Alap Setup Script
# This script sets up the development environment

set -e

echo "🦅 Alap-Alap Setup"
echo "=================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip
pip install -e ".[dev]"

# Install Camoufox browser
echo ""
echo "Installing Camoufox browser..."
camoufox fetch

echo ""
echo "✅ Setup complete!"
echo ""
echo "To activate the virtual environment:"
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "  source venv/Scripts/activate"
else
    echo "  source venv/bin/activate"
fi
echo ""
echo "To start the API server:"
echo "  python -m alap_alap.api.server"

#!/bin/bash
set -e

# Change to the HydraBot root (parent of scripts/)
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "🐍 HydraBot - Self-expanding AI Assistant via Telegram"
echo "======================================================="

# Find python
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "❌ Python not found! Please install Python 3.9+"
    exit 1
fi

echo "   Python: $($PYTHON --version)"

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    $PYTHON -m venv venv
fi

# Activate venv (supports Windows Git Bash and Unix)
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install / update dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt -q --disable-pip-version-check

# Create necessary directories
mkdir -p tools mcp_servers

echo ""
echo "🤖 Starting bot..."
echo ""

python main.py

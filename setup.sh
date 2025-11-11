#!/bin/bash
# Quick Start Script for Bug Arena

echo "Battle Bug Setup"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi
echo "Python found: $(python3 --version)"
echo "Creating virtual environment..."
python3 -m venv .venv
echo "Virtual environment created!"

echo "Activating virtual environment..."
source .venv/bin/activate
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env and add your LLM API key before running the application."
fi

echo ""
echo "Creating directories..."
mkdir -p uploads database

echo ""
echo "Initializing database..."
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all(); print(' Database created!')"

echo ""
echo "Setup complete!"
echo ""
echo "To start the application:"
echo "1. Edit .env and add your Anthropic API key"
echo "2. Run: source .venv/bin/activate"
echo "3. Run: python run.py"
echo "4. Open http://localhost:5000 in your browser"
echo ""
echo "For Docker deployment:"
echo "1. Edit .env and add your LLM API keys"
echo "2. Run: docker-compose up -d --build"
echo ""

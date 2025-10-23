#!/bin/bash

echo "===================================="
echo "Co-Tester Setup Script - Linux/Mac"
echo "===================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed or not in PATH"
    echo "Please install Python 3.8+ from your package manager or https://python.org"
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    print_error "Node.js is not installed or not in PATH"
    echo "Please install Node.js 20.x from your package manager or https://nodejs.org"
    exit 1
fi

print_status "Step 1: Creating virtual environment..."
python3 -m venv co-tester-env
if [ $? -ne 0 ]; then
    print_error "Failed to create virtual environment"
    exit 1
fi
print_success "Virtual environment created"

print_status "Step 2: Activating virtual environment..."
source co-tester-env/bin/activate

print_status "Step 3: Upgrading pip..."
python -m pip install --upgrade pip

print_status "Step 4: Installing Python dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    print_error "Failed to install Python dependencies"
    exit 1
fi
print_success "Python dependencies installed"

print_status "Step 5: Installing Node.js dependencies..."
npm install
if [ $? -ne 0 ]; then
    print_error "Failed to install Node.js dependencies"
    exit 1
fi
print_success "Node.js dependencies installed"

print_status "Step 6: Installing Playwright browsers..."
npx playwright install
if [ $? -ne 0 ]; then
    print_warning "Playwright browser installation failed"
    echo "You may need to run this manually later"
else
    print_success "Playwright browsers installed"
fi

print_status "Step 7: Installing Playwright system dependencies (Linux only)..."
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    npx playwright install-deps
    if [ $? -eq 0 ]; then
        print_success "Playwright system dependencies installed"
    else
        print_warning "Failed to install Playwright system dependencies"
        echo "You may need to run 'sudo npx playwright install-deps' manually"
    fi
fi

print_status "Step 8: Creating environment file..."
if [ ! -f .env ]; then
    cat > .env << EOL
# Flask Configuration
SECRET_KEY=your-secret-key-change-this-in-production
FLASK_ENV=development

# Google AI Configuration
GOOGLE_API_KEY=your-google-gemini-api-key
GOOGLE_API_MODEL=gemini-2.0-flash-exp

# Jira OAuth Configuration (Optional)
JIRA_CLIENT_ID=your-jira-client-id
JIRA_CLIENT_SECRET=your-jira-client-secret
JIRA_CALLBACK_URL=http://localhost:5000/api/jira/oauth/callback

# Rate Limiting
DAILY_LLM_LIMIT=20

# Admin Access
ADMIN_EMAILS=admin@yourcompany.com
EOL
    print_success "Created .env file with default values"
    print_warning "Please edit .env file with your actual configuration values"
else
    print_warning ".env file already exists, skipping creation"
fi

print_status "Step 9: Initializing database..."
python -c "from app import app; app.app_context().push(); from app import db; db.create_all(); print('Database initialized successfully')"
if [ $? -eq 0 ]; then
    print_success "Database initialized"
else
    print_warning "Database initialization failed"
    echo "You may need to run this manually later"
fi

echo ""
echo "===================================="
print_success "Setup completed successfully!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Edit the .env file with your configuration values"
echo "2. Get a Google AI API key from https://ai.google.dev/"
echo "3. (Optional) Setup Jira OAuth for full integration"
echo ""
echo "To start the application:"
echo "  source co-tester-env/bin/activate"
echo "  python app.py"
echo ""
echo "Then open http://localhost:5000 in your browser"
echo ""
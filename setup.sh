#!/bin/bash
# ===================================
# Co-Tester One-Click Setup Script
# ===================================
# Platform: Linux/macOS (Bash)
# Last Updated: 2025-11-07
# ===================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================"
echo -e "   Co-Tester Setup & Installation      "
echo -e "========================================${NC}"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to print step
print_step() {
    echo -e "\n${YELLOW}>>> $1${NC}"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print error
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# ===================================
# Step 1: Check Prerequisites
# ===================================
print_step "Checking prerequisites..."

# Check Python
if command_exists python3; then
    PYTHON_VERSION=$(python3 --version)
    print_success "Python found: $PYTHON_VERSION"
    PYTHON_CMD="python3"
elif command_exists python; then
    PYTHON_VERSION=$(python --version)
    print_success "Python found: $PYTHON_VERSION"
    PYTHON_CMD="python"
else
    print_error "Python not found! Please install Python 3.11+ from https://www.python.org/"
    exit 1
fi

# Check Node.js
if command_exists node; then
    NODE_VERSION=$(node --version)
    print_success "Node.js found: $NODE_VERSION"
else
    print_error "Node.js not found! Please install Node.js 20.x from https://nodejs.org/"
    exit 1
fi

# Check npm
if command_exists npm; then
    NPM_VERSION=$(npm --version)
    print_success "npm found: v$NPM_VERSION"
else
    print_error "npm not found! Please install Node.js which includes npm"
    exit 1
fi

# Check Git (optional but recommended)
if command_exists git; then
    GIT_VERSION=$(git --version)
    print_success "Git found: $GIT_VERSION"
else
    print_warning "Git not found (optional)"
fi

# ===================================
# Step 2: Create Virtual Environment
# ===================================
print_step "Setting up Python virtual environment..."

if [ -d "venv" ]; then
    print_warning "Virtual environment already exists, skipping creation"
else
    $PYTHON_CMD -m venv venv
    if [ $? -eq 0 ]; then
        print_success "Virtual environment created"
    else
        print_error "Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
print_step "Activating virtual environment..."
source venv/bin/activate
if [ $? -eq 0 ]; then
    print_success "Virtual environment activated"
else
    print_error "Failed to activate virtual environment"
    exit 1
fi

# ===================================
# Step 3: Upgrade pip
# ===================================
print_step "Upgrading pip..."
python -m pip install --upgrade pip
if [ $? -eq 0 ]; then
    print_success "pip upgraded successfully"
else
    print_warning "pip upgrade failed, continuing anyway"
fi

# ===================================
# Step 4: Install Python Dependencies
# ===================================
print_step "Installing Python dependencies from requirements.txt..."
echo -e "${GRAY}This may take a few minutes...${NC}"

pip install -r requirements.txt
if [ $? -eq 0 ]; then
    print_success "Python dependencies installed successfully"
else
    print_error "Failed to install Python dependencies"
    exit 1
fi

# ===================================
# Step 5: Install browser-use
# ===================================
print_step "Installing browser-use (AI-powered browser automation)..."
pip install git+https://github.com/browser-use/browser-use.git
if [ $? -eq 0 ]; then
    print_success "browser-use installed successfully"
else
    print_warning "browser-use installation failed (optional feature)"
fi

# ===================================
# Step 6: Install Node.js Dependencies
# ===================================
print_step "Installing Node.js dependencies (including XState for MBT)..."
npm install
if [ $? -eq 0 ]; then
    print_success "Node.js dependencies installed successfully"
else
    print_error "Failed to install Node.js dependencies"
    exit 1
fi

# ===================================
# Step 7: Install Playwright Browsers
# ===================================
print_step "Installing Playwright browsers (Chromium, Firefox, WebKit)..."
echo -e "${GRAY}This may take several minutes and download ~500MB...${NC}"

npx playwright install
if [ $? -eq 0 ]; then
    print_success "Playwright browsers installed successfully"
else
    print_warning "Playwright browser installation failed, trying with dependencies..."
    npx playwright install --with-deps
    if [ $? -eq 0 ]; then
        print_success "Playwright browsers installed with system dependencies"
    else
        print_error "Failed to install Playwright browsers"
        # Continue anyway as this might work on next try
    fi
fi

# ===================================
# Step 8: Install Tesseract (Optional)
# ===================================
print_step "Checking for Tesseract OCR..."

if command_exists tesseract; then
    TESSERACT_VERSION=$(tesseract --version 2>&1 | head -n1)
    print_success "Tesseract found: $TESSERACT_VERSION"
else
    print_warning "Tesseract OCR not found (optional for OCR features)"
    echo -e "${GRAY}Install with:${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "${GRAY}  brew install tesseract${NC}"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo -e "${GRAY}  sudo apt-get install tesseract-ocr${NC}"
    fi
fi

# ===================================
# Step 9: Setup Environment File
# ===================================
print_step "Setting up environment configuration..."

if [ -f ".env" ]; then
    print_warning ".env file already exists, skipping creation"
else
    cat > .env << EOF
# ===================================
# Co-Tester Environment Configuration
# ===================================
# Created: $(date)
# ===================================

# Flask Configuration
SECRET_KEY=your-secret-key-change-this-$RANDOM
FLASK_APP=app.py
FLASK_ENV=development
DEBUG=True

# Database Configuration
DATABASE_URL=sqlite:///instance/db.sqlite3

# AI API Keys (Required for AI features)
# Get your key from: https://makersuite.google.com/app/apikey
GEMINI_API_KEY=

# OpenAI (Optional - for alternative AI backend)
# Get your key from: https://platform.openai.com/api-keys
OPENAI_API_KEY=

# Azure OpenAI (Optional)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
AZURE_OPENAI_DEPLOYMENT=

# OAuth Configuration (Optional)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Jira Configuration (Optional)
JIRA_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=

# Tesseract OCR Path (Optional - usually auto-detected)
# TESSERACT_CMD=/usr/bin/tesseract
EOF
    
    print_success ".env file created"
    print_warning "Please edit .env file and add your API keys (especially GEMINI_API_KEY)"
fi

# ===================================
# Step 10: Initialize Database
# ===================================
print_step "Initializing database..."

if [ -f "instance/db.sqlite3" ]; then
    print_warning "Database already exists, skipping initialization"
else
    # Create instance directory if it doesn't exist
    mkdir -p instance
    
    # Initialize database
    python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized successfully')"
    if [ $? -eq 0 ]; then
        print_success "Database initialized"
    else
        print_warning "Database initialization failed, will retry on first run"
    fi
fi

# ===================================
# Step 11: Verify Installation
# ===================================
print_step "Verifying installation..."

echo -e "\n${GRAY}Checking Python packages...${NC}"
python -c "import flask, playwright, google.generativeai, sqlalchemy; print('✓ Core Python packages OK')"
if [ $? -eq 0 ]; then
    print_success "Python packages verified"
else
    print_warning "Some Python packages may be missing"
fi

echo -e "\n${GRAY}Checking Node.js packages...${NC}"
if npm list xstate --depth=0 >/dev/null 2>&1; then
    print_success "XState installed (MBT feature ready)"
else
    print_warning "XState not found (MBT feature may not work)"
fi

# ===================================
# Installation Complete
# ===================================
echo ""
echo -e "${GREEN}========================================"
echo -e "   Installation Complete! 🎉          "
echo -e "========================================${NC}"
echo ""

echo -e "${CYAN}Next Steps:${NC}"
echo -e "${NC}1. Edit .env file and add your GEMINI_API_KEY"
echo -e "${GRAY}   Get your key from: https://makersuite.google.com/app/apikey${NC}"
echo ""
echo -e "${NC}2. Start the application:"
echo -e "${YELLOW}   python app.py${NC}"
echo ""
echo -e "${NC}3. Open your browser:"
echo -e "${YELLOW}   http://localhost:5000${NC}"
echo ""
echo -e "${NC}4. Access Model-Based Testing:"
echo -e "${YELLOW}   http://localhost:5000/mbt${NC}"
echo ""

echo -e "${CYAN}Documentation:${NC}"
echo -e "${GRAY}- Installation Guide: INSTALLATION.md"
echo -e "- Dependencies Reference: DEPENDENCIES.md"
echo -e "- MBT Practical Guide: docs/MBT-PRACTICAL-GUIDE.md"
echo -e "- Complete MBT Docs: docs/MBT-COMPLETE-README.md${NC}"
echo ""

echo -e "${CYAN}Troubleshooting:${NC}"
echo -e "${GRAY}- If you encounter issues, check INSTALLATION.md"
echo -e "- Make sure to activate virtual environment: source venv/bin/activate"
echo -e "- Verify .env file has your GEMINI_API_KEY set${NC}"
echo ""

# Ask if user wants to start the app
read -p "Would you like to start the application now? (Y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "${GREEN}Starting Co-Tester...${NC}"
    echo -e "${GRAY}Press Ctrl+C to stop the server${NC}"
    echo ""
    python app.py
else
    echo ""
    echo -e "${GREEN}Setup complete! Run 'python app.py' when ready.${NC}"
    echo ""
fi

# ===================================
# Co-Tester One-Click Setup Script
# ===================================
# Platform: Windows (PowerShell)
# Last Updated: 2025-11-07
# ===================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Co-Tester Setup & Installation      " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Function to check if command exists
function Test-Command {
    param($Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

# Function to print step
function Write-Step {
    param($Message)
    Write-Host "`n>>> $Message" -ForegroundColor Yellow
}

# Function to print success
function Write-Success {
    param($Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

# Function to print error
function Write-Error-Custom {
    param($Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

# Function to print warning
function Write-Warning-Custom {
    param($Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

# ===================================
# Step 1: Check Prerequisites
# ===================================
Write-Step "Checking prerequisites..."

# Check Python
if (Test-Command python) {
    $pythonVersion = python --version
    Write-Success "Python found: $pythonVersion"
} else {
    Write-Error-Custom "Python not found! Please install Python 3.11+ from https://www.python.org/"
    exit 1
}

# Check Node.js
if (Test-Command node) {
    $nodeVersion = node --version
    Write-Success "Node.js found: $nodeVersion"
} else {
    Write-Error-Custom "Node.js not found! Please install Node.js 20.x from https://nodejs.org/"
    exit 1
}

# Check npm
if (Test-Command npm) {
    $npmVersion = npm --version
    Write-Success "npm found: v$npmVersion"
} else {
    Write-Error-Custom "npm not found! Please install Node.js which includes npm"
    exit 1
}

# Check Git (optional but recommended)
if (Test-Command git) {
    $gitVersion = git --version
    Write-Success "Git found: $gitVersion"
} else {
    Write-Warning-Custom "Git not found (optional)"
}

# ===================================
# Step 2: Create Virtual Environment
# ===================================
Write-Step "Setting up Python virtual environment..."

if (Test-Path "venv") {
    Write-Warning-Custom "Virtual environment already exists, skipping creation"
} else {
    python -m venv venv
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Virtual environment created"
    } else {
        Write-Error-Custom "Failed to create virtual environment"
        exit 1
    }
}

# Activate virtual environment
Write-Step "Activating virtual environment..."
& ".\venv\Scripts\Activate.ps1"
if ($LASTEXITCODE -eq 0) {
    Write-Success "Virtual environment activated"
} else {
    Write-Error-Custom "Failed to activate virtual environment"
    exit 1
}

# ===================================
# Step 3: Upgrade pip
# ===================================
Write-Step "Upgrading pip..."
python -m pip install --upgrade pip
if ($LASTEXITCODE -eq 0) {
    Write-Success "pip upgraded successfully"
} else {
    Write-Warning-Custom "pip upgrade failed, continuing anyway"
}

# ===================================
# Step 4: Install Python Dependencies
# ===================================
Write-Step "Installing Python dependencies from requirements.txt..."
Write-Host "This may take a few minutes..." -ForegroundColor Gray

pip install -r requirements.txt
if ($LASTEXITCODE -eq 0) {
    Write-Success "Python dependencies installed successfully"
} else {
    Write-Error-Custom "Failed to install Python dependencies"
    exit 1
}

# ===================================
# Step 5: Install browser-use
# ===================================
Write-Step "Installing browser-use (AI-powered browser automation)..."
pip install git+https://github.com/browser-use/browser-use.git
if ($LASTEXITCODE -eq 0) {
    Write-Success "browser-use installed successfully"
} else {
    Write-Warning-Custom "browser-use installation failed (optional feature)"
}

# ===================================
# Step 6: Install Node.js Dependencies
# ===================================
Write-Step "Installing Node.js dependencies (including XState for MBT)..."
npm install
if ($LASTEXITCODE -eq 0) {
    Write-Success "Node.js dependencies installed successfully"
} else {
    Write-Error-Custom "Failed to install Node.js dependencies"
    exit 1
}

# ===================================
# Step 7: Install Playwright Browsers
# ===================================
Write-Step "Installing Playwright browsers (Chromium, Firefox, WebKit)..."
Write-Host "This may take several minutes and download ~500MB..." -ForegroundColor Gray

npx playwright install
if ($LASTEXITCODE -eq 0) {
    Write-Success "Playwright browsers installed successfully"
} else {
    Write-Warning-Custom "Playwright browser installation failed, trying with dependencies..."
    npx playwright install --with-deps
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Playwright browsers installed with system dependencies"
    } else {
        Write-Error-Custom "Failed to install Playwright browsers"
    }
}

# ===================================
# Step 8: Setup Environment File
# ===================================
Write-Step "Setting up environment configuration..."

if (Test-Path ".env") {
    Write-Warning-Custom ".env file already exists, skipping creation"
} else {
    # Create .env template
    @"
# ===================================
# Co-Tester Environment Configuration
# ===================================
# Created: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# ===================================

# Flask Configuration
SECRET_KEY=your-secret-key-change-this-$(Get-Random -Maximum 99999)
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

# Tesseract OCR Path (Optional - set if not in PATH)
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
"@ | Out-File -FilePath ".env" -Encoding UTF8
    
    Write-Success ".env file created"
    Write-Warning-Custom "Please edit .env file and add your API keys (especially GEMINI_API_KEY)"
}

# ===================================
# Step 9: Initialize Database
# ===================================
Write-Step "Initializing database..."

if (Test-Path "instance\db.sqlite3") {
    Write-Warning-Custom "Database already exists, skipping initialization"
} else {
    # Create instance directory if it doesn't exist
    if (-not (Test-Path "instance")) {
        New-Item -ItemType Directory -Path "instance" | Out-Null
    }
    
    # Initialize database
    python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized successfully')"
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Database initialized"
    } else {
        Write-Warning-Custom "Database initialization failed, will retry on first run"
    }
}

# ===================================
# Step 10: Verify Installation
# ===================================
Write-Step "Verifying installation..."

Write-Host "`nChecking Python packages..." -ForegroundColor Gray
python -c "import flask, playwright, google.generativeai, sqlalchemy; print('✓ Core Python packages OK')"
if ($LASTEXITCODE -eq 0) {
    Write-Success "Python packages verified"
} else {
    Write-Warning-Custom "Some Python packages may be missing"
}

Write-Host "`nChecking Node.js packages..." -ForegroundColor Gray
$xstateCheck = npm list xstate --depth=0 2>&1
if ($xstateCheck -like "*xstate*") {
    Write-Success "XState installed (MBT feature ready)"
} else {
    Write-Warning-Custom "XState not found (MBT feature may not work)"
}

# ===================================
# Installation Complete
# ===================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "   Installation Complete! 🎉          " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Edit .env file and add your GEMINI_API_KEY" -ForegroundColor White
Write-Host "   Get your key from: https://makersuite.google.com/app/apikey" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Start the application:" -ForegroundColor White
Write-Host "   python app.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Open your browser:" -ForegroundColor White
Write-Host "   http://localhost:5000" -ForegroundColor Yellow
Write-Host ""
Write-Host "4. Access Model-Based Testing:" -ForegroundColor White
Write-Host "   http://localhost:5000/mbt" -ForegroundColor Yellow
Write-Host ""

Write-Host "Documentation:" -ForegroundColor Cyan
Write-Host "- Installation Guide: INSTALLATION.md" -ForegroundColor Gray
Write-Host "- Dependencies Reference: DEPENDENCIES.md" -ForegroundColor Gray
Write-Host "- MBT Practical Guide: docs/MBT-PRACTICAL-GUIDE.md" -ForegroundColor Gray
Write-Host "- Complete MBT Docs: docs/MBT-COMPLETE-README.md" -ForegroundColor Gray
Write-Host ""

Write-Host "Troubleshooting:" -ForegroundColor Cyan
Write-Host "- If you encounter issues, check INSTALLATION.md" -ForegroundColor Gray
Write-Host "- Make sure to activate virtual environment: .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "- Verify .env file has your GEMINI_API_KEY set" -ForegroundColor Gray
Write-Host ""

# Ask if user wants to start the app
$startApp = Read-Host "Would you like to start the application now? (Y/N)"
if ($startApp -eq "Y" -or $startApp -eq "y") {
    Write-Host ""
    Write-Host "Starting Co-Tester..." -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
    Write-Host ""
    python app.py
} else {
    Write-Host ""
    Write-Host "Setup complete! Run 'python app.py' when ready." -ForegroundColor Green
    Write-Host ""
}

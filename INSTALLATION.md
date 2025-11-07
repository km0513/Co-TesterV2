# Co-Tester Installation Guide

## Prerequisites

Before installing Co-Tester, ensure you have the following installed:

- **Python 3.11+** (Required)
- **Node.js 20.x** (Required for MBT features)
- **npm 9.0+** (Comes with Node.js)
- **Git** (Recommended)

## Installation Steps

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Co-Tester
```

### 2. Set Up Python Environment

#### Option A: Using Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# On Windows (CMD):
.\venv\Scripts\activate.bat

# On macOS/Linux:
source venv/bin/activate
```

#### Option B: Using System Python

Skip the virtual environment step and proceed directly to installing dependencies.

### 3. Install Python Dependencies

```bash
# Install from requirements.txt
pip install -r requirements.txt

# Install browser-use (AI-powered automation)
pip install git+https://github.com/browser-use/browser-use.git
```

### 4. Install Node.js Dependencies

```bash
# Install all npm packages including XState for MBT
npm install
```

### 5. Install Playwright Browsers

```bash
# Install Chromium, Firefox, and WebKit browsers
playwright install

# Or install specific browser only
playwright install chromium
```

### 6. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Copy template (if exists)
cp .env.example .env

# Or create manually
touch .env
```

Add the following configuration to `.env`:

```env
# Flask Configuration
SECRET_KEY=your-secret-key-here
FLASK_APP=app.py
FLASK_ENV=development
DEBUG=True

# Database Configuration
DATABASE_URL=sqlite:///instance/db.sqlite3

# AI API Keys (Required for AI features)
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key  # Optional

# Azure OpenAI (Optional)
AZURE_OPENAI_ENDPOINT=your-azure-endpoint
AZURE_OPENAI_KEY=your-azure-key
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# OAuth Configuration (Optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Jira Configuration (Optional)
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token

# Tesseract OCR (Optional - set if not in PATH)
TESSERACT_CMD=/path/to/tesseract
```

### 7. Initialize Database

```bash
# Run database migrations
flask db upgrade

# Or if running migrations for the first time
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### 8. Run the Application

```bash
# Development mode
python app.py

# Or using Flask CLI
flask run

# Production mode (using gunicorn)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

The application will be available at: `http://localhost:5000`

## Verifying Installation

### 1. Check Python Dependencies

```bash
pip list | grep -E "Flask|playwright|google-generativeai|langchain"
```

### 2. Check Node Dependencies

```bash
npm list xstate @xstate/test @playwright/test
```

### 3. Check Playwright Browsers

```bash
playwright --version
```

### 4. Test the Application

Navigate to:
- Main Dashboard: `http://localhost:5000`
- Model-Based Testing: `http://localhost:5000/mbt`
- API Documentation: `http://localhost:5000/api`

## Common Issues & Solutions

### Issue: Playwright browsers not installed

**Solution:**
```bash
playwright install
```

### Issue: Missing Python dependencies

**Solution:**
```bash
pip install -r requirements.txt --force-reinstall
```

### Issue: npm dependencies not installed

**Solution:**
```bash
rm -rf node_modules package-lock.json
npm install
```

### Issue: Database not initialized

**Solution:**
```bash
rm instance/db.sqlite3  # Remove old database
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Issue: Tesseract not found (OCR features)

**Windows:**
```bash
# Download and install from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH or set TESSERACT_CMD in .env
```

**macOS:**
```bash
brew install tesseract
```

**Linux:**
```bash
sudo apt-get install tesseract-ocr
```

### Issue: Import errors with browser-use

**Solution:**
```bash
pip uninstall browser-use
pip install git+https://github.com/browser-use/browser-use.git
```

## Feature-Specific Setup

### Model-Based Testing (MBT)

Ensure the following are installed:

1. **Python dependencies** (already in requirements.txt):
   - Flask
   - SQLAlchemy
   - google-generativeai

2. **Node.js dependencies** (in package.json):
   - xstate
   - @xstate/test
   - @xstate/graph
   - @playwright/test

3. **Environment variables**:
   ```env
   GEMINI_API_KEY=your-key-here
   ```

### AI-Powered Testing

Required API keys:
```env
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key  # Optional
```

### Browser Automation

Install browsers:
```bash
playwright install chromium firefox webkit
```

## Development Setup

For active development, install additional tools:

```bash
# Code formatting
pip install black

# Linting
pip install flake8 pylint

# Type checking
pip install mypy

# Testing
pip install pytest pytest-cov pytest-playwright pytest-asyncio
```

## Production Deployment

### Using Gunicorn (Recommended)

```bash
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

### Using Docker (Optional)

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
RUN apt-get install -y nodejs

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy files
COPY requirements.txt package.json ./
COPY . .

# Install dependencies
RUN pip install -r requirements.txt
RUN npm install
RUN playwright install-deps
RUN playwright install

# Run application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## Next Steps

After installation:

1. **Explore the UI**: Navigate to `http://localhost:5000`
2. **Read the MBT Guide**: See `docs/MBT-PRACTICAL-GUIDE.md`
3. **Try Examples**: Run `python examples/mbt_working_example.py`
4. **Configure Integrations**: Set up Jira, Azure, etc.

## Getting Help

- **Documentation**: See `docs/` folder
- **MBT Guide**: `docs/MBT-PRACTICAL-GUIDE.md`
- **API Routes**: `docs/MBT-COMPLETE-README.md`
- **Examples**: `examples/mbt_working_example.py`

## System Requirements

### Minimum:
- **CPU**: 2 cores
- **RAM**: 4GB
- **Disk**: 2GB free space

### Recommended:
- **CPU**: 4+ cores
- **RAM**: 8GB+
- **Disk**: 5GB+ free space

## License

[Your License Here]

---

**Last Updated**: 2025-01-07  
**Co-Tester Version**: 1.0.0

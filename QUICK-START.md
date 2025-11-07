# 🚀 Co-Tester Quick Start Guide

Get Co-Tester up and running in **under 5 minutes** with our one-click setup scripts!

---

## Prerequisites

Before running the setup script, ensure you have:

- ✅ **Python 3.11+** installed ([Download](https://www.python.org/downloads/))
- ✅ **Node.js 20.x** installed ([Download](https://nodejs.org/))
- ✅ **Git** installed (recommended) ([Download](https://git-scm.com/))

---

## One-Click Setup

### Windows (PowerShell)

```powershell
# Clone the repository (if not already done)
git clone <repository-url>
cd Co-Tester

# Run the setup script
.\setup.ps1
```

**Note**: If you get an execution policy error, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### macOS/Linux (Bash)

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd Co-Tester

# Make the script executable
chmod +x setup.sh

# Run the setup script
./setup.sh
```

---

## What the Setup Script Does

The automated setup script will:

1. ✅ Check prerequisites (Python, Node.js, npm)
2. ✅ Create Python virtual environment
3. ✅ Install all Python dependencies (~90 packages)
4. ✅ Install browser-use (AI automation)
5. ✅ Install Node.js dependencies (XState for MBT)
6. ✅ Install Playwright browsers (~500MB download)
7. ✅ Create `.env` configuration file
8. ✅ Initialize SQLite database
9. ✅ Verify installation
10. ✅ Optionally start the application

**Estimated time**: 3-5 minutes (depending on internet speed)

---

## Post-Setup Configuration

### 1. Add Your API Keys

Edit the `.env` file and add your Gemini API key:

```env
GEMINI_API_KEY=your-actual-api-key-here
```

**Get your Gemini API key**: https://makersuite.google.com/app/apikey

### 2. (Optional) Configure Additional Services

```env
# OpenAI (alternative AI backend)
OPENAI_API_KEY=your-openai-key

# Jira Integration
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-token
```

---

## Starting the Application

### Automatic Start (if you chose "Yes" during setup)

The application will start automatically and be available at:
- **Main Dashboard**: http://localhost:5000
- **Model-Based Testing**: http://localhost:5000/mbt
- **API Testing**: http://localhost:5000/api

### Manual Start

#### Windows (PowerShell)
```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Start the application
python app.py
```

#### macOS/Linux (Bash)
```bash
# Activate virtual environment
source venv/bin/activate

# Start the application
python app.py
```

---

## Verifying Installation

### Check Python Dependencies
```bash
pip list | grep -E "Flask|playwright|google-generativeai"
```

### Check Node.js Dependencies
```bash
npm list xstate @xstate/test @playwright/test
```

### Check Playwright Browsers
```bash
npx playwright --version
```

### Test the Application
1. Start the app: `python app.py`
2. Open browser: http://localhost:5000
3. Navigate to MBT: http://localhost:5000/mbt
4. Check API docs: http://localhost:5000/api

---

## Quick Feature Tour

### 1. Model-Based Testing (MBT)
Navigate to: http://localhost:5000/mbt

**Features**:
- Create state machines visually
- AI-powered state discovery from URLs
- Generate test paths automatically
- Execute Playwright tests
- View execution history

### 2. AI-Powered Testing
Navigate to: http://localhost:5000

**Features**:
- Smart test case generation
- Auto-healing selectors
- Bug builder with AI assistance
- Test report generation

### 3. Browser Automation
Use Playwright/Selenium integration:
- Record user interactions
- Generate test scripts
- Execute cross-browser tests
- Screenshot comparison

---

## Troubleshooting

### Issue: Script execution disabled (Windows)
**Solution**:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue: Permission denied (macOS/Linux)
**Solution**:
```bash
chmod +x setup.sh
```

### Issue: Python/Node.js not found
**Solution**:
- Install Python 3.11+: https://www.python.org/downloads/
- Install Node.js 20.x: https://nodejs.org/

### Issue: Playwright browsers not installed
**Solution**:
```bash
npx playwright install
```

### Issue: Database errors
**Solution**:
```bash
# Delete old database
rm instance/db.sqlite3

# Reinitialize
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Issue: Import errors
**Solution**:
```bash
# Activate virtual environment first
# Windows:
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

# Then reinstall
pip install -r requirements.txt
```

---

## Manual Setup (Alternative)

If you prefer to set up manually without the script:

```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate (Windows)
.\venv\Scripts\Activate.ps1
# Or (macOS/Linux)
source venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt
pip install git+https://github.com/browser-use/browser-use.git

# 4. Install Node.js dependencies
npm install

# 5. Install Playwright browsers
npx playwright install

# 6. Create .env file
cp .env.example .env
# Edit .env and add your API keys

# 7. Initialize database
python -c "from app import app, db; app.app_context().push(); db.create_all()"

# 8. Start application
python app.py
```

---

## Next Steps

After setup is complete:

1. **📚 Read the Documentation**
   - `INSTALLATION.md` - Detailed installation guide
   - `DEPENDENCIES.md` - Complete dependency reference
   - `docs/MBT-PRACTICAL-GUIDE.md` - MBT usage guide
   - `docs/MBT-COMPLETE-README.md` - Complete MBT documentation

2. **🧪 Try Examples**
   ```bash
   python examples/mbt_working_example.py
   ```

3. **🎨 Explore the UI**
   - Main Dashboard: http://localhost:5000
   - MBT Interface: http://localhost:5000/mbt
   - API Testing: http://localhost:5000/api

4. **⚙️ Configure Integrations**
   - Set up Jira integration
   - Configure Azure services
   - Add OAuth providers

---

## Getting Help

- **Documentation**: See `docs/` folder
- **Issues**: Check `INSTALLATION.md` troubleshooting section
- **MBT Guide**: `docs/MBT-PRACTICAL-GUIDE.md`
- **API Reference**: `docs/MBT-COMPLETE-README.md`

---

## System Requirements

### Minimum
- **CPU**: 2 cores
- **RAM**: 4GB
- **Disk**: 2GB free space
- **OS**: Windows 10+, macOS 10.15+, Ubuntu 20.04+

### Recommended
- **CPU**: 4+ cores
- **RAM**: 8GB+
- **Disk**: 5GB+ free space
- **Internet**: For downloading dependencies and AI API calls

---

## What's Included

After setup, you'll have:

- ✅ Flask web application (http://localhost:5000)
- ✅ SQLite database with all tables
- ✅ Python virtual environment with 90+ packages
- ✅ Node.js dependencies including XState for MBT
- ✅ Playwright browsers (Chromium, Firefox, WebKit)
- ✅ AI integration (Gemini AI ready)
- ✅ Model-Based Testing feature (16 API endpoints)
- ✅ Browser automation tools
- ✅ Complete documentation

---

## Success! 🎉

Your Co-Tester installation is complete! You're now ready to:

- Create AI-powered tests
- Build state machines for MBT
- Generate test cases automatically
- Run cross-browser automation
- Integrate with Jira and other tools

**Happy Testing!** 🚀

---

**Last Updated**: November 7, 2025  
**Version**: 1.0.0

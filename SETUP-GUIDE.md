# 🎯 Co-Tester One-Click Setup - Visual Guide

## Overview

This guide shows you **exactly** how to get Co-Tester running with minimal effort using our automated setup scripts.

---

## 📺 Setup Process Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    START HERE                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  Do you have Python 3.11+ installed?  │
        └───────────────────────────────────────┘
                   ↓ NO              ↓ YES
      ┌─────────────────┐           ↓
      │ Install Python  │           ↓
      │   python.org    │           ↓
      └─────────────────┘           ↓
                   ↓                ↓
        ┌───────────────────────────────────────┐
        │  Do you have Node.js 20.x installed?  │
        └───────────────────────────────────────┘
                   ↓ NO              ↓ YES
      ┌─────────────────┐           ↓
      │ Install Node.js │           ↓
      │   nodejs.org    │           ↓
      └─────────────────┘           ↓
                   ↓                ↓
        ┌───────────────────────────────────────┐
        │       Clone Co-Tester Repository      │
        │   git clone <repo-url>                │
        │   cd Co-Tester                        │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │       Choose Your Platform            │
        └───────────────────────────────────────┘
                            ↓
           ┌────────────────┴────────────────┐
           ↓                                 ↓
    ┌─────────────┐                  ┌─────────────┐
    │   WINDOWS   │                  │ MAC / LINUX │
    │             │                  │             │
    │ setup.ps1   │                  │  setup.sh   │
    └─────────────┘                  └─────────────┘
           ↓                                 ↓
    ┌─────────────┐                  ┌─────────────┐
    │ PowerShell  │                  │    Bash     │
    │ .\setup.ps1 │                  │ ./setup.sh  │
    └─────────────┘                  └─────────────┘
           ↓                                 ↓
           └────────────────┬────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │    Automated Installation Process     │
        │  (3-5 minutes, depending on speed)    │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │ ✅ Prerequisites Check                 │
        │ ✅ Virtual Environment Setup           │
        │ ✅ Python Dependencies (90 packages)   │
        │ ✅ Node.js Dependencies (9 packages)   │
        │ ✅ Playwright Browsers (~500MB)        │
        │ ✅ .env Configuration File             │
        │ ✅ Database Initialization             │
        │ ✅ Installation Verification           │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │    Edit .env with your API keys       │
        │    (especially GEMINI_API_KEY)        │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │   Start application? (Y/N)            │
        └───────────────────────────────────────┘
                ↓ YES              ↓ NO
      ┌─────────────────┐    ┌──────────────┐
      │ Auto-start app  │    │  Exit setup  │
      │ localhost:5000  │    │ Run manually │
      └─────────────────┘    └──────────────┘
                ↓                    ↓
      ┌─────────────────┐    ┌──────────────┐
      │  Open Browser   │    │ python app.py│
      │ localhost:5000  │    └──────────────┘
      └─────────────────┘            ↓
                ↓                    ↓
                └────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │        🎉 CO-TESTER RUNNING!          │
        │    http://localhost:5000              │
        │    http://localhost:5000/mbt          │
        └───────────────────────────────────────┘
```

---

## 🪟 Windows Setup (Step-by-Step)

### Step 1: Open PowerShell
```
Right-click Start Menu → Windows PowerShell
```

### Step 2: Navigate to Downloads or desired location
```powershell
cd C:\Users\YourName\Downloads
```

### Step 3: Clone repository
```powershell
git clone https://github.com/km0513/Co-TesterV2.git
cd Co-TesterV2
```

### Step 4: Run setup script
```powershell
.\setup.ps1
```

**If you get execution policy error:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup.ps1
```

### Step 5: Watch the magic happen! ✨
```
========================================
   Co-Tester Setup & Installation
========================================

>>> Checking prerequisites...
✓ Python found: Python 3.11.5
✓ Node.js found: v20.10.0
✓ npm found: v10.2.3

>>> Setting up Python virtual environment...
✓ Virtual environment created
✓ Virtual environment activated

>>> Upgrading pip...
✓ pip upgraded successfully

>>> Installing Python dependencies...
This may take a few minutes...
✓ Python dependencies installed successfully

>>> Installing Node.js dependencies...
✓ Node.js dependencies installed successfully

>>> Installing Playwright browsers...
This may take several minutes...
✓ Playwright browsers installed successfully

>>> Setting up environment configuration...
✓ .env file created
⚠ Please edit .env file and add your API keys

>>> Initializing database...
✓ Database initialized

>>> Verifying installation...
✓ Python packages verified
✓ XState installed (MBT feature ready)

========================================
   Installation Complete! 🎉
========================================

Would you like to start the application now? (Y/N)
```

---

## 🍎 macOS/Linux Setup (Step-by-Step)

### Step 1: Open Terminal
```
Cmd + Space → type "Terminal" → Enter
```

### Step 2: Navigate to desired location
```bash
cd ~/Downloads
```

### Step 3: Clone repository
```bash
git clone https://github.com/km0513/Co-TesterV2.git
cd Co-TesterV2
```

### Step 4: Make script executable
```bash
chmod +x setup.sh
```

### Step 5: Run setup script
```bash
./setup.sh
```

### Step 6: Watch the installation! 🚀
```
========================================
   Co-Tester Setup & Installation
========================================

>>> Checking prerequisites...
✓ Python found: Python 3.11.5
✓ Node.js found: v20.10.0
✓ npm found: v10.2.3

>>> Setting up Python virtual environment...
✓ Virtual environment created

>>> Installing Python dependencies...
✓ Python dependencies installed successfully

>>> Installing Node.js dependencies...
✓ Node.js dependencies installed successfully

>>> Installing Playwright browsers...
✓ Playwright browsers installed successfully

>>> Setting up environment configuration...
✓ .env file created

>>> Initializing database...
✓ Database initialized

========================================
   Installation Complete! 🎉
========================================

Would you like to start the application now? (Y/N)
```

---

## 🎬 What Happens During Setup?

### Phase 1: Prerequisite Check (10 seconds)
```
Checking for:
├── Python 3.11+    → Required
├── Node.js 20.x    → Required  
├── npm 9.0+        → Required
└── Git             → Optional (recommended)
```

### Phase 2: Environment Setup (30 seconds)
```
Creating:
├── Virtual environment (venv/)
├── Activating environment
└── Upgrading pip to latest
```

### Phase 3: Python Dependencies (2-3 minutes)
```
Installing 90+ packages:
├── Flask & extensions (9 packages)
├── Database (SQLAlchemy, alembic)
├── AI/ML (Gemini, OpenAI, LangChain)
├── Browser automation (Playwright, Selenium)
├── Document processing
├── Image processing & OCR
└── Many more...
```

### Phase 4: Node.js Dependencies (30 seconds)
```
Installing:
├── xstate (State machine library)
├── @xstate/test (Test generation)
├── @xstate/graph (Graph algorithms)
├── @playwright/test (Test runner)
└── TypeScript support
```

### Phase 5: Playwright Browsers (2-3 minutes)
```
Downloading ~500MB:
├── Chromium browser
├── Firefox browser
└── WebKit browser
```

### Phase 6: Configuration (5 seconds)
```
Creating:
├── .env file with templates
├── instance/ directory
└── SQLite database
```

### Phase 7: Verification (10 seconds)
```
Checking:
├── Python packages import successfully
├── XState modules available
└── All dependencies present
```

---

## 🔑 Post-Setup: API Key Configuration

After setup completes, edit `.env` file:

### Windows
```powershell
notepad .env
```

### macOS
```bash
nano .env
```

### Linux
```bash
nano .env
# or
vim .env
```

### Add Your API Key
```env
# Required for AI features
GEMINI_API_KEY=AIzaSy...your-actual-key-here

# Optional
OPENAI_API_KEY=sk-...your-openai-key
```

**Get Gemini API Key**: https://makersuite.google.com/app/apikey

---

## 🚀 Starting Co-Tester

### Option 1: Auto-start (if you chose "Y" during setup)
```
Application starts automatically
Open browser: http://localhost:5000
```

### Option 2: Manual start

**Windows:**
```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

**macOS/Linux:**
```bash
source venv/bin/activate
python app.py
```

---

## 🌐 Access Points

Once running, access these URLs:

```
┌────────────────────────────────────────────────┐
│  Main Dashboard                                │
│  http://localhost:5000                         │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  Model-Based Testing (MBT)                     │
│  http://localhost:5000/mbt                     │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  API Testing                                   │
│  http://localhost:5000/api                     │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  Bug Builder                                   │
│  http://localhost:5000/bug-builder             │
└────────────────────────────────────────────────┘
```

---

## 🎯 First Steps After Setup

### 1. Explore the Dashboard
```
http://localhost:5000
```
- See all available features
- Check system status
- Navigate to different tools

### 2. Try Model-Based Testing
```
http://localhost:5000/mbt
```
- Create a simple state machine
- Use AI to discover states
- Generate test paths
- Execute tests

### 3. Test API Testing
```
http://localhost:5000/api
```
- Enter an API endpoint
- Generate test cases
- Execute requests
- View responses

### 4. Read Documentation
```
- QUICK-START.md (you are here!)
- INSTALLATION.md (detailed guide)
- DEPENDENCIES.md (all packages)
- docs/MBT-PRACTICAL-GUIDE.md (MBT tutorial)
```

---

## ❗ Troubleshooting

### Issue: "Python not found"
**Solution**: Install Python 3.11+ from https://www.python.org/downloads/

### Issue: "Node.js not found"  
**Solution**: Install Node.js 20.x from https://nodejs.org/

### Issue: "Execution policy" error (Windows)
**Solution**:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue: "Permission denied" (macOS/Linux)
**Solution**:
```bash
chmod +x setup.sh
```

### Issue: Playwright browsers not installed
**Solution**:
```bash
npx playwright install
```

### Issue: Database errors
**Solution**:
```bash
rm instance/db.sqlite3
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Issue: Import errors
**Solution**:
```bash
# Activate venv first!
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate      # macOS/Linux

# Then reinstall
pip install -r requirements.txt
```

---

## 📊 Installation Time Breakdown

| Phase | Time | Activity |
|-------|------|----------|
| Prerequisites | 10s | Checking Python, Node.js, npm |
| Environment | 30s | Creating virtual environment |
| Python Deps | 2-3m | Installing 90+ packages |
| Node Deps | 30s | Installing 9 packages |
| Browsers | 2-3m | Downloading Playwright browsers |
| Config | 5s | Creating .env and database |
| Verify | 10s | Checking installation |
| **Total** | **5-7m** | **Complete setup** |

*Note: Times may vary based on internet speed and system performance*

---

## ✅ Success Indicators

You'll know setup succeeded when you see:

```
✓ Python found: Python 3.11.x
✓ Node.js found: v20.x.x
✓ Virtual environment created
✓ Python dependencies installed successfully
✓ Node.js dependencies installed successfully
✓ Playwright browsers installed successfully
✓ .env file created
✓ Database initialized
✓ Python packages verified
✓ XState installed (MBT feature ready)

========================================
   Installation Complete! 🎉
========================================
```

---

## 🎉 You're Ready!

**Congratulations!** Co-Tester is now installed and ready to use.

### Next Steps:
1. ✅ Setup complete
2. 🔑 Add GEMINI_API_KEY to .env
3. 🚀 Start app: `python app.py`
4. 🌐 Open: http://localhost:5000
5. 📚 Read: docs/MBT-PRACTICAL-GUIDE.md
6. 🧪 Try examples: `python examples/mbt_working_example.py`

**Happy Testing! 🚀**

---

**Last Updated**: November 7, 2025  
**Version**: 1.0.0  
**Platform**: Windows, macOS, Linux

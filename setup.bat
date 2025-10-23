@echo off
echo ====================================
echo Co-Tester Setup Script - Windows
echo ====================================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo Error: Node.js is not installed or not in PATH
    echo Please install Node.js 20.x from https://nodejs.org
    pause
    exit /b 1
)

echo Step 1: Creating virtual environment...
python -m venv co-tester-env
if errorlevel 1 (
    echo Error: Failed to create virtual environment
    pause
    exit /b 1
)

echo Step 2: Activating virtual environment...
call co-tester-env\Scripts\activate.bat

echo Step 3: Upgrading pip...
python -m pip install --upgrade pip

echo Step 4: Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install Python dependencies
    pause
    exit /b 1
)

echo Step 5: Installing Node.js dependencies...
npm install
if errorlevel 1 (
    echo Error: Failed to install Node.js dependencies
    pause
    exit /b 1
)

echo Step 6: Installing Playwright browsers...
npx playwright install
if errorlevel 1 (
    echo Warning: Playwright browser installation failed
    echo You may need to run this manually later
)

echo Step 7: Creating environment file...
if not exist .env (
    echo Creating .env file from template...
    (
        echo # Flask Configuration
        echo SECRET_KEY=your-secret-key-change-this-in-production
        echo FLASK_ENV=development
        echo.
        echo # Google AI Configuration
        echo GOOGLE_API_KEY=your-google-gemini-api-key
        echo GOOGLE_API_MODEL=gemini-2.0-flash-exp
        echo.
        echo # Jira OAuth Configuration ^(Optional^)
        echo JIRA_CLIENT_ID=your-jira-client-id
        echo JIRA_CLIENT_SECRET=your-jira-client-secret
        echo JIRA_CALLBACK_URL=http://localhost:5000/api/jira/oauth/callback
        echo.
        echo # Rate Limiting
        echo DAILY_LLM_LIMIT=20
        echo.
        echo # Admin Access
        echo ADMIN_EMAILS=admin@yourcompany.com
    ) > .env
    echo Created .env file with default values
    echo Please edit .env file with your actual configuration values
) else (
    echo .env file already exists, skipping creation
)

echo Step 8: Initializing database...
python -c "from app import app; app.app_context().push(); from app import db; db.create_all(); print('Database initialized successfully')"
if errorlevel 1 (
    echo Warning: Database initialization failed
    echo You may need to run this manually later
)

echo.
echo ====================================
echo Setup completed successfully!
echo ====================================
echo.
echo Next steps:
echo 1. Edit the .env file with your configuration values
echo 2. Get a Google AI API key from https://ai.google.dev/
echo 3. ^(Optional^) Setup Jira OAuth for full integration
echo.
echo To start the application:
echo   co-tester-env\Scripts\activate
echo   python app.py
echo.
echo Then open http://localhost:5000 in your browser
echo.
pause
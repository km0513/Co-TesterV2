@echo off
REM Co-Tester Update Script for Users (Windows)

echo ==================================
echo Co-Tester Update Script
echo ==================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Docker is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo 📥 Pulling latest Co-Tester version...
docker-compose pull

if errorlevel 1 (
    echo ❌ Error: Failed to pull update!
    pause
    exit /b 1
)

echo.
echo 🔄 Restarting with new version...
docker-compose up -d

if errorlevel 1 (
    echo ❌ Error: Failed to restart!
    pause
    exit /b 1
)

echo.
echo ✅ Update complete!
echo.
echo Co-Tester is now running the latest version.
echo Access it at: http://localhost:5000
echo.

REM Show recent logs
echo Recent logs:
docker-compose logs --tail=20

echo.
echo To view full logs: docker-compose logs -f
echo.
pause

@echo off
REM Build and publish Docker image script for Windows

setlocal enabledelayedexpansion

REM Configuration
set IMAGE_NAME=co-tester
set DOCKER_USERNAME=your-dockerhub-username
REM Change DOCKER_USERNAME to your Docker Hub username

REM Get version from argument or default to "latest"
if "%~1"=="" (
    set VERSION=latest
) else (
    set VERSION=%~1
)

echo ==================================
echo Building Co-Tester Docker Image
echo ==================================
echo Image: %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION%
echo.

REM Build the image
echo Step 1: Building Docker image...
docker build -t %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION% .

if errorlevel 1 (
    echo ERROR: Docker build failed!
    exit /b 1
)

REM Also tag as latest if version is specified
if not "%VERSION%"=="latest" (
    echo Step 2: Tagging as latest...
    docker tag %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION% %DOCKER_USERNAME%/%IMAGE_NAME%:latest
)

echo.
echo Build complete!
echo.
echo To test locally:
echo   docker run -p 5000:5000 --env-file .env %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION%
echo.
echo To publish to Docker Hub:
echo   1. docker login
echo   2. docker push %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION%
if not "%VERSION%"=="latest" (
    echo   3. docker push %DOCKER_USERNAME%/%IMAGE_NAME%:latest
)
echo.

REM Ask if user wants to publish
set /p PUBLISH="Do you want to publish to Docker Hub now? (y/n): "
if /i "%PUBLISH%"=="y" (
    echo Publishing to Docker Hub...
    docker push %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION%
    if not "%VERSION%"=="latest" (
        docker push %DOCKER_USERNAME%/%IMAGE_NAME%:latest
    )
    echo.
    echo ✅ Published successfully!
    echo.
    echo Users can now pull with:
    echo   docker pull %DOCKER_USERNAME%/%IMAGE_NAME%:%VERSION%
)

endlocal

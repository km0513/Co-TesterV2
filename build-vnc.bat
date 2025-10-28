@echo off
REM Build and publish Co-Tester Docker image with VNC support
REM Usage: build-vnc.bat [version]
REM Example: build-vnc.bat v1.0.9-vnc

SET IMAGE_NAME=kishore1305/co-tester
SET VERSION=%1

REM If no version provided, use default
IF "%VERSION%"=="" SET VERSION=v1.0.9-vnc

echo ========================================
echo Building Co-Tester VNC Docker Image
echo ========================================
echo Image: %IMAGE_NAME%:%VERSION%
echo Also tagging as: vnc
echo ========================================
echo.

REM Build the image
echo Building Docker image...
docker build -f Dockerfile.vnc -t %IMAGE_NAME%:%VERSION% -t %IMAGE_NAME%:vnc .

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Docker build failed!
    echo Check the error messages above.
    exit /b 1
)

echo.
echo ✅ Build successful!
echo.
echo Image tags:
echo   - %IMAGE_NAME%:%VERSION%
echo   - %IMAGE_NAME%:vnc
echo.

REM Ask if user wants to publish
SET /P PUBLISH="Do you want to publish to Docker Hub? (y/n): "

IF /I "%PUBLISH%"=="y" (
    echo.
    echo Publishing to Docker Hub...
    docker push %IMAGE_NAME%:%VERSION%
    docker push %IMAGE_NAME%:vnc
    
    IF %ERRORLEVEL% EQU 0 (
        echo.
        echo ✅ Successfully published!
        echo.
        echo Users can now pull with:
        echo   docker pull %IMAGE_NAME%:vnc
        echo   docker pull %IMAGE_NAME%:%VERSION%
    ) ELSE (
        echo.
        echo ❌ Push failed!
        echo Make sure you're logged in: docker login
    )
) ELSE (
    echo.
    echo Skipping publish.
    echo To publish later, run:
    echo   docker push %IMAGE_NAME%:%VERSION%
    echo   docker push %IMAGE_NAME%:vnc
)

echo.
echo ========================================
echo VNC Image Build Complete
echo ========================================
echo.
echo To run with VNC enabled:
echo   docker run -p 5000:5000 -p 5900:5900 --env-file .env -e ENABLE_VNC=true %IMAGE_NAME%:vnc
echo.
echo Then connect with VNC Viewer to: localhost:5900
echo Password: cotester (or set VNC_PASSWORD in .env)
echo.

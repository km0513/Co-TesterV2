# Co-Tester - Quick Start Guide

## Prerequisites

- **Docker Desktop for Windows** (Download: https://www.docker.com/products/docker-desktop)
- **Google API Key** (Get free: https://aistudio.google.com/apikey)

---

## Setup Instructions

### Step 1: Install Docker Desktop

1. Download and install Docker Desktop from the link above
2. Start Docker Desktop
3. Wait for the whale icon in system tray to show "Docker Desktop is running"

### Step 2: Create Working Folder

Open PowerShell and run:

```powershell
mkdir Co-Tester-App
cd Co-Tester-App
```

### Step 3: Create Environment File

Create a file named `.env` in the `Co-Tester-App` folder with this content:

```env
SECRET_KEY=change-this-to-any-random-long-string-min-32-characters
GOOGLE_API_KEY=your-google-gemini-api-key-here
GOOGLE_API_MODEL=gemini-2.0-flash-exp
PLAYWRIGHT_HEADLESS=true
```

**Important Notes:**
- **NO spaces around the `=` sign**
- **NO quotes around values**
- Replace `your-google-gemini-api-key-here` with your actual API key
- Replace `change-this-to-any-random-long-string-min-32-characters` with any random text (at least 32 characters)
- Set `PLAYWRIGHT_HEADLESS=true` for headless mode (no browser window) or `false` to see the browser

**Example `.env` file:**
```env
SECRET_KEY=my-super-secret-key-for-testing-2025-cotester-app-xyz123
GOOGLE_API_KEY=AIzaSyABC123XYZ456-your-actual-key-here
GOOGLE_API_MODEL=gemini-2.0-flash-exp
PLAYWRIGHT_HEADLESS=true
```

### Step 4: Run Co-Tester

In PowerShell (in the `Co-Tester-App` folder), run:

```powershell
docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

**First time:** Docker will download the app (~2GB) - takes 5-10 minutes depending on internet speed.

**You'll see:**
```
INFO     [apscheduler.scheduler] Scheduler started
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://172.17.0.2:5000
```

### Step 5: Access Co-Tester

Open your browser and go to:
```
http://localhost:5000
```

---

## Common Commands

### Stop Co-Tester
Press `Ctrl + C` in the PowerShell window

### Run in Background (Detached Mode)
```powershell
docker run -d -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

### View Logs (if running in background)
```powershell
docker logs -f <container-id>
```

To find container ID:
```powershell
docker ps
```

### Stop Background Container
```powershell
docker stop <container-id>
```

### Update to Latest Version
```powershell
docker pull kishore1305/co-tester:latest
docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

---

## Troubleshooting

### 🎭 Playwright Browser Mode

**Want to see the browser window while automation runs?**

Set `PLAYWRIGHT_HEADLESS=false` in your `.env` file:

```env
PLAYWRIGHT_HEADLESS=false
```

**When to use headless vs headed:**
- ✅ **Headless (`true`)**: Recommended for Docker, faster, uses less resources, good for automated tests
- 🖥️ **Headed (`false`)**: For interactive features (Bug Builder, Test Generator)

**⚠️ Important for Interactive Features:**
If you're using **Bug Builder** or **Test Generator** (features where you manually click and interact with browser), you need to use the **VNC-enabled Docker image**:

```powershell
docker pull kishore1305/co-tester:vnc
docker run -p 5000:5000 -p 5900:5900 --env-file .env -e ENABLE_VNC=true -e PLAYWRIGHT_HEADLESS=false kishore1305/co-tester:vnc
```

Then:
1. Download a **FREE VNC Viewer**:
   - **TigerVNC** (Recommended): https://github.com/TigerVNC/tigervnc/releases
   - **TightVNC**: https://www.tightvnc.com/download.php
   - **RealVNC Viewer**: https://www.realvnc.com/en/connect/download/viewer/ (free for personal use)
2. Connect to `localhost:5900` with password `cotester`
3. You'll see and interact with the browser inside Docker!

📖 **See `DOCKER_DISPLAY_MODES.md` for detailed explanation of all options.**

### ❌ Error: "port is already allocated"
Another application is using port 5000. Use a different port:
```powershell
docker run -p 5001:5000 --env-file .env kishore1305/co-tester:latest
```
Then access at: http://localhost:5001

### ❌ Error: "variable contains whitespaces"
Your `.env` file has spaces around `=`. Fix example:
- ❌ Wrong: `GOOGLE_API_KEY = your-key`
- ✅ Correct: `GOOGLE_API_KEY=your-key`

### ❌ Error: "Cannot connect to Docker daemon"
Docker Desktop is not running. Start Docker Desktop and wait for it to fully start.

### ❌ Application doesn't load
Wait 30 seconds for the app to fully start after running the command.

---

## Need Help?

Contact the Co-Tester team or check the full documentation at: [Your documentation link]

---

**Note:** All your data (test cases, reports, uploads) is stored inside the Docker container. To persist data across restarts, use the docker-compose method (see advanced documentation).

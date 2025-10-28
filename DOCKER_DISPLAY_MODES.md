# Docker Display Modes for Co-Tester

## Understanding the Problem

Co-Tester has **two types of features** that require different browser setups:

### 🤖 Automated Features (Headless OK)
- API Testing
- Test Report Generation
- Context Building
- Background automation tasks

### 👆 Interactive Features (Visible Browser REQUIRED)
- **Bug Builder** - User manually clicks and records steps
- **Test Generator** - User performs actions to create tests
- **Playwright Codegen** - Records user interactions
- Any feature where YOU need to interact with the browser

---

## The Challenge

When running in Docker:
- Your source code is **protected** (stays inside container)
- But the browser is **also inside** the container
- You can't click on a browser that's inside Docker! ❌

---

## Solution: Two Docker Run Modes

### Mode 1: Headless Mode (For Automated Features)
**Use when**: Running automated tests, API testing, background tasks

```powershell
docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

**What happens**:
- Browser runs inside Docker with Xvfb (virtual display)
- No browser window appears
- Faster performance
- Perfect for automation

**Environment Setting**: `PLAYWRIGHT_HEADLESS=true`

---

### Mode 2: Host Display Mode (For Interactive Features)
**Use when**: Bug Builder, Test Generator, Playwright recording, manual interaction

#### 🪟 **On Windows** (Your Current OS)

Unfortunately, Docker on Windows **cannot directly share the display** like Linux does. You have **three options**:

---

#### **Option A: Use VNC to View Inside Docker** (RECOMMENDED)

This adds a VNC server to Docker so you can see and interact with the browser remotely.

**Setup Steps**:

1. **Pull VNC-enabled Docker image**:
   ```powershell
   docker pull kishore1305/co-tester:vnc
   ```

2. **Run with VNC port exposed**:
   ```powershell
   docker run -p 5000:5000 -p 5900:5900 --env-file .env -e PLAYWRIGHT_HEADLESS=false -e ENABLE_VNC=true kishore1305/co-tester:vnc
   ```

3. **Download VNC Viewer** (100% FREE options):
   - **TigerVNC Viewer** (Recommended): https://github.com/TigerVNC/tigervnc/releases
     * Completely free and open source
     * Lightweight (~5MB)
     * Works on Windows, Mac, Linux
   - **TightVNC Viewer**: https://www.tightvnc.com/download.php
     * Free for personal and commercial use
     * Small download (~2MB)
   - **RealVNC Viewer**: https://www.realvnc.com/en/connect/download/viewer/
     * Free for non-commercial use
     * Feature-rich (~10MB)

4. **Connect to VNC**:
   - Open VNC Viewer
   - Connect to: `localhost:5900`
   - Password: `cotester` (default, can be changed via env var `VNC_PASSWORD`)

5. **Interact with Browser**:
   - You'll see a desktop window
   - Browser appears there
   - Click, type, interact normally
   - Playwright records your actions ✅

**Pros**:
- ✅ Source code stays protected in Docker
- ✅ You can see and interact with the browser
- ✅ Works on Windows, Mac, Linux
- ✅ Real-time interaction for Bug Builder

**Cons**:
- Requires VNC viewer software (free download)
- Slight latency (usually imperceptible)
- Extra port to expose

---

#### **Option B: Use X Server on Windows** (Advanced)

Install an X Server on Windows to display Docker's browser windows.

**Setup Steps**:

1. **Install VcXsrv** (X Server for Windows):
   - Download: https://sourceforge.net/projects/vcxsrv/
   - Install with default settings

2. **Launch XLaunch** (comes with VcXsrv):
   - Multiple windows: ✅
   - Display number: 0
   - Start no client: ✅
   - Disable access control: ✅ (IMPORTANT)

3. **Allow firewall** (if prompted)

4. **Get your IP address**:
   ```powershell
   ipconfig
   # Look for "IPv4 Address" under your network adapter (usually 192.168.x.x)
   ```

5. **Run Docker with display**:
   ```powershell
   docker run -p 5000:5000 --env-file .env -e DISPLAY=192.168.1.100:0.0 -e PLAYWRIGHT_HEADLESS=false kishore1305/co-tester:latest
   ```
   *(Replace `192.168.1.100` with YOUR IP from step 4)*

6. **Browser appears on your Windows desktop!** ✅

**Pros**:
- ✅ Browser appears directly on your screen
- ✅ No VNC viewer needed
- ✅ Native performance

**Cons**:
- Complex setup (X Server, firewall, IP)
- Security risk (X Server allows remote connections)
- Can break if IP address changes

---

#### **Option C: Run Locally for Development** (Easiest but Exposes Code)

If you're developing/debugging and don't mind seeing the source code temporarily:

1. **Install Python** (3.11+)
2. **Clone repository** or extract source
3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Create `.env` file** with your settings

5. **Run locally**:
   ```powershell
   python app.py
   ```

6. **Set `PLAYWRIGHT_HEADLESS=false`** in `.env`

7. **Browser appears on your screen!** ✅

**Pros**:
- ✅ Simplest setup
- ✅ Best debugging experience
- ✅ Direct interaction

**Cons**:
- ❌ Source code exposed (defeats Docker protection)
- ❌ Requires Python installation
- ❌ Each user needs to set up dependencies

---

## Quick Decision Guide

```
Do you need Bug Builder / Test Generator / Manual Recording?
│
├─ YES → Need visible, interactive browser
│   │
│   ├─ Want to protect source code?
│   │   │
│   │   ├─ YES → Option A: VNC (RECOMMENDED)
│   │   │        Run: docker run -p 5000:5000 -p 5900:5900 -e ENABLE_VNC=true ...
│   │   │
│   │   └─ NO → Option C: Run locally
│   │            Run: python app.py
│   │
│   └─ Advanced user, want native display?
│       └─ Option B: X Server (complex)
│
└─ NO → Only automated testing
    └─ Use headless mode (default)
        Run: docker run -p 5000:5000 --env-file .env ...
        Set: PLAYWRIGHT_HEADLESS=true
```

---

## Environment Variables Summary

Add these to your `.env` file:

```env
# Browser display mode
PLAYWRIGHT_HEADLESS=false  # Set to false for interactive features

# VNC settings (Option A only)
ENABLE_VNC=true            # Enable VNC server
VNC_PASSWORD=cotester      # Change for security

# X Server settings (Option B only)
DISPLAY=192.168.1.100:0.0  # Your Windows IP address
```

---

## Troubleshooting

### "Browser doesn't appear" (Headless=false in Docker)
- **Problem**: Docker can't show windows on Windows display by default
- **Solution**: Use Option A (VNC) or Option B (X Server)

### "Can't interact with browser in VNC"
- **Check**: Is `PLAYWRIGHT_HEADLESS=false`?
- **Check**: Is `ENABLE_VNC=true`?
- **Check**: Connected to correct port (5900)?

### "VNC connection refused"
- **Check**: Did you expose port 5900? `-p 5900:5900`
- **Check**: Is Docker container running? `docker ps`
- **Check**: Firewall blocking VNC port?

### "Browser crashes immediately"
- **Check**: Using VNC-enabled image? `kishore1305/co-tester:vnc`
- **Check**: Xvfb running inside container? (should be automatic)

### "X Server connection failed" (Option B)
- **Check**: Is VcXsrv running? Look for system tray icon
- **Check**: Did you disable access control in XLaunch?
- **Check**: Is your IP address correct? Run `ipconfig`
- **Check**: Firewall allows incoming connections?

---

## Performance Comparison

| Scenario | Mode | Docker Run Command | Performance |
|----------|------|-------------------|-------------|
| Automated tests | Headless in Docker | `docker run -p 5000:5000 --env-file .env` | ⚡⚡⚡ Fastest |
| Bug Builder | VNC to Docker | `docker run -p 5000:5000 -p 5900:5900 -e ENABLE_VNC=true` | ⚡⚡ Good |
| Bug Builder | X Server | `docker run -e DISPLAY=IP:0.0` | ⚡⚡ Good |
| Development | Local Python | `python app.py` | ⚡⚡⚡ Fastest |

---

## Recommended Setup for Different Users

### 👤 **End Users** (No coding, just using the tool)
- **For automation**: Headless mode (default)
- **For Bug Builder**: VNC mode (Option A)
- **Never** run locally (keeps code protected)

### 👨‍💻 **Developers** (Your team members)
- **For development**: Run locally (Option C)
- **For testing**: Headless Docker
- **For demos**: VNC mode

### 🏢 **Enterprise Deployment**
- **Production**: Headless mode only
- **Debug access**: VNC with strong password
- **Consider**: Dedicated VNC port per instance

---

## Next Steps

1. **For Automated Features**: You're all set! Current setup works perfectly
2. **For Bug Builder**: Choose Option A (VNC) or B (X Server)
3. **Need VNC image**: Let me know, I'll build `v1.0.9-vnc` with VNC support
4. **Questions**: Ask about any option before deciding

---

## Summary

**The Problem**: Docker hides the browser, but Bug Builder needs user interaction

**The Solution**: 
- **Automated features** → Use current Docker setup (headless)
- **Interactive features** → Use VNC (Option A) to see/interact with browser
- **Source code** → Stays protected in Docker in both cases! ✅

You **cannot** have a visible, interactive browser on your Windows desktop from Docker without either:
- Option A: VNC (recommended, keeps code protected)
- Option B: X Server (complex, keeps code protected)
- Option C: Running locally (simple, but exposes code)

**My Recommendation**: I build a VNC-enabled Docker image for you! 🚀

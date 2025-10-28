# Co-Tester Docker - Quick Reference

## Which Docker Image Should I Use?

### 🤖 Standard Image: `kishore1305/co-tester:latest`
**Use for:**
- ✅ API Testing
- ✅ Test Report Generation  
- ✅ Automated test execution
- ✅ Context Building
- ✅ Any feature that doesn't need you to click on browser

**Run command:**
```powershell
docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

**Environment:**
```env
PLAYWRIGHT_HEADLESS=true
```

---

### 🖥️ VNC Image: `kishore1305/co-tester:vnc`
**Use for:**
- ✅ Bug Builder (manual recording)
- ✅ Test Generator (recording interactions)
- ✅ Playwright Codegen
- ✅ Any feature where YOU need to interact with browser

**Run command:**
```powershell
docker run -p 5000:5000 -p 5900:5900 --env-file .env -e ENABLE_VNC=true -e PLAYWRIGHT_HEADLESS=false kishore1305/co-tester:vnc
```

**Environment:**
```env
PLAYWRIGHT_HEADLESS=false
ENABLE_VNC=true
VNC_PASSWORD=cotester
```

**Connect with VNC:**
1. Download [VNC Viewer](https://www.realvnc.com/en/connect/download/viewer/)
2. Open VNC Viewer
3. Connect to: `localhost:5900`
4. Password: `cotester`
5. You'll see the browser - click and interact normally!

---

## Quick Comparison

| Feature | Standard Image | VNC Image |
|---------|---------------|-----------|
| Size | ~2GB | ~2.2GB |
| Ports | 5000 | 5000, 5900 |
| Browser visible? | ❌ No | ✅ Yes (via VNC) |
| User interaction? | ❌ No | ✅ Yes |
| Bug Builder? | ❌ No | ✅ Yes |
| Test Generator? | ❌ No | ✅ Yes |
| Automated tests? | ✅ Yes | ✅ Yes |
| Performance | ⚡⚡⚡ Fast | ⚡⚡ Good |
| Complexity | Simple | Medium (VNC setup) |

---

## When to Switch

### Start with Standard Image
If you're just using automated features, API testing, or generating reports.

### Switch to VNC Image when:
- You click "Bug Builder" and need to record manual steps
- You use "Test Generator" to capture interactions
- You need to see what the browser is doing
- You're debugging a specific issue

---

## Environment Variables Cheat Sheet

### Required (both images):
```env
SECRET_KEY=your-secret-key-here
GOOGLE_API_KEY=your-google-api-key
GOOGLE_API_MODEL=gemini-2.0-flash-exp
```

### Browser control:
```env
# Headless = no browser window (faster)
PLAYWRIGHT_HEADLESS=true

# Headed = visible browser (for interaction)
PLAYWRIGHT_HEADLESS=false
```

### VNC control (VNC image only):
```env
# Enable VNC server
ENABLE_VNC=true

# Set VNC password (change for security!)
VNC_PASSWORD=cotester
```

---

## Common Commands

### Pull images:
```powershell
# Standard image
docker pull kishore1305/co-tester:latest

# VNC image
docker pull kishore1305/co-tester:vnc
```

### Run standard (automated features):
```powershell
docker run -d -p 5000:5000 --name cotester --env-file .env kishore1305/co-tester:latest
```

### Run VNC (interactive features):
```powershell
docker run -d -p 5000:5000 -p 5900:5900 --name cotester-vnc --env-file .env -e ENABLE_VNC=true -e PLAYWRIGHT_HEADLESS=false kishore1305/co-tester:vnc
```

### Stop container:
```powershell
docker stop cotester
# or
docker stop cotester-vnc
```

### Remove container:
```powershell
docker rm cotester
# or  
docker rm cotester-vnc
```

### View logs:
```powershell
docker logs cotester
# or
docker logs cotester-vnc
```

### Check if VNC is running:
```powershell
docker logs cotester-vnc | findstr VNC
# Should show: "VNC server started on port 5900"
```

---

## Troubleshooting

### VNC connection refused
- **Check**: Container running with VNC port exposed? `docker ps | findstr 5900`
- **Check**: VNC enabled? Look in logs: `docker logs cotester-vnc | findstr VNC`
- **Fix**: Restart with correct command (include `-p 5900:5900 -e ENABLE_VNC=true`)

### Can't interact with browser in VNC
- **Check**: Is `PLAYWRIGHT_HEADLESS=false`?
- **Check**: Using VNC image? `docker ps` should show `kishore1305/co-tester:vnc`
- **Fix**: Stop container, run with correct image and environment variables

### Browser doesn't appear
- **Check**: Are you using standard image for Bug Builder?
- **Fix**: Switch to VNC image
- **Note**: Standard image has browser inside, but you can't see it (that's normal!)

### VNC screen is blank
- **Wait**: 10-15 seconds after container starts
- **Check**: Xvfb running? `docker exec cotester-vnc ps aux | findstr Xvfb`
- **Check**: Fluxbox running? `docker exec cotester-vnc ps aux | findstr fluxbox`

---

## Pro Tips

### Tip 1: Use Different Containers for Different Purposes
```powershell
# Standard for automated work
docker run -d -p 5000:5000 --name cotester-auto --env-file .env kishore1305/co-tester:latest

# VNC for Bug Builder
docker run -d -p 5001:5000 -p 5900:5900 --name cotester-interactive --env-file .env -e ENABLE_VNC=true kishore1305/co-tester:vnc
```

### Tip 2: Change VNC Password
```powershell
docker run -p 5000:5000 -p 5900:5900 --env-file .env -e ENABLE_VNC=true -e VNC_PASSWORD=MySecurePass123 kishore1305/co-tester:vnc
```

### Tip 3: Disable VNC When Not Needed (saves resources)
```powershell
# VNC image but VNC disabled = same as standard image
docker run -p 5000:5000 --env-file .env -e ENABLE_VNC=false kishore1305/co-tester:vnc
```

### Tip 4: Check VNC Logs
```powershell
# Inside container
docker exec cotester-vnc cat /app/logs/x11vnc.log
```

---

## Summary

- **Automated features** → Standard image, headless mode ✅
- **Interactive features** → VNC image, headed mode + VNC ✅
- **Source code** → Always protected (stays in Docker) ✅
- **Your choice** → Pick the right tool for the job 🎯

For more details, see `DOCKER_DISPLAY_MODES.md`

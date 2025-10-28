# Playwright Browser Modes Guide

Co-Tester supports both **headless** and **headed** browser modes for Playwright automation.

## 🎭 What's the Difference?

### Headless Mode (`PLAYWRIGHT_HEADLESS=true`)
- ✅ **No browser window** - runs in background
- ✅ **Faster** - less resource usage
- ✅ **Better for Docker** - works without display server
- ✅ **Production ready** - recommended for deployments
- ⚠️ **Harder to debug** - can't see what's happening

### Headed Mode (`PLAYWRIGHT_HEADLESS=false`)
- 🖥️ **Visible browser** - see automation in real-time
- 🐛 **Easier debugging** - watch what goes wrong
- 📹 **Better screenshots** - see actual rendering
- ⚠️ **Slower** - more resource intensive
- ⚠️ **Needs display** - requires X server (Xvfb in Docker)

---

## 🔧 How to Switch Modes

### Edit your `.env` file:

**For Headless (Recommended for Docker):**
```env
PLAYWRIGHT_HEADLESS=true
```

**For Headed (Good for local debugging):**
```env
PLAYWRIGHT_HEADLESS=false
```

Then restart the application:
```powershell
# If using docker run
Ctrl+C  # Stop current container
docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest

# If using docker-compose
docker-compose restart
```

---

## 📋 When to Use Each Mode

### Use Headless Mode When:
- ✅ Running in Docker container
- ✅ Running on CI/CD pipeline
- ✅ Running on server without GUI
- ✅ Performance is important
- ✅ Running many tests in parallel

### Use Headed Mode When:
- 🐛 Debugging test failures
- 👀 Want to see what the automation is doing
- 🎓 Learning how Co-Tester works
- 📸 Recording demos or tutorials
- 🔍 Investigating unexpected behavior

---

## 🐳 Docker Considerations

### Docker with Xvfb (v1.0.7+)

Our Docker image includes **Xvfb** (X Virtual Framebuffer), which allows headed browsers to run even without a physical display!

**How it works:**
```
Your Docker Container:
┌─────────────────────────┐
│  Xvfb (Virtual Display) │ ← Creates fake screen
│         ↓               │
│  Chromium Browser       │ ← Runs normally
│         ↓               │
│  Screenshots/Videos     │ ← Captures output
└─────────────────────────┘
```

**What this means:**
- ✅ You can use `PLAYWRIGHT_HEADLESS=false` in Docker!
- ✅ Browser thinks it has a real screen (Xvfb)
- ✅ All features work (screenshots, video recording, etc.)
- ✅ No actual GUI window (it's virtual)

### Before v1.0.7 (Old Docker Images)

If you're using an older image without Xvfb:
- ⚠️ Must use `PLAYWRIGHT_HEADLESS=true`
- ❌ Headed mode will crash with "Missing X server" error
- 📦 Update to latest version: `docker pull kishore1305/co-tester:latest`

---

## 🔍 Troubleshooting

### Error: "Missing X server or $DISPLAY"

**Cause:** Trying to run headed mode without display server.

**Solutions:**

1. **Switch to headless mode (easiest):**
   ```env
   PLAYWRIGHT_HEADLESS=true
   ```

2. **Update to Docker image v1.0.7+:**
   ```powershell
   docker pull kishore1305/co-tester:latest
   ```

3. **Verify Xvfb is running (in Docker):**
   ```bash
   docker exec <container-id> ps aux | grep Xvfb
   # Should show: Xvfb :99 -screen 0 1920x1080x24 ...
   ```

### Headed mode works locally but not in Docker

**Cause:** Your local machine has a real display, Docker needs virtual display (Xvfb).

**Solution:** Ensure you're using Docker image v1.0.7+ which includes Xvfb.

### Browser window not appearing (headed mode locally)

**Check:**
1. Is `PLAYWRIGHT_HEADLESS=false` in your `.env`?
2. Restart the application after changing the setting
3. Check Docker logs for errors:
   ```powershell
   docker logs <container-id>
   ```

---

## 💡 Pro Tips

### Tip 1: Different modes for different environments
```bash
# Local development
PLAYWRIGHT_HEADLESS=false

# Docker deployment  
PLAYWRIGHT_HEADLESS=true
```

### Tip 2: Override environment variable temporarily
```powershell
# Linux/Mac
PLAYWRIGHT_HEADLESS=false docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest

# Windows PowerShell
$env:PLAYWRIGHT_HEADLESS="false"; docker run -p 5000:5000 --env-file .env kishore1305/co-tester:latest
```

### Tip 3: Check current mode
The application logs will show:
```
🌐 Launching browser...
Mode: Headless (PLAYWRIGHT_HEADLESS=true)
```

---

## 📊 Performance Comparison

| Aspect | Headless | Headed (with Xvfb) |
|--------|----------|-------------------|
| **Speed** | ⚡ Fast | 🐢 ~10-20% slower |
| **Memory** | 💾 ~200MB | 💾 ~250-300MB |
| **CPU** | 🔋 Low | 🔋 Medium |
| **Docker Size** | 📦 Same | 📦 Same |
| **Debugging** | ❌ Hard | ✅ Easy |
| **CI/CD Ready** | ✅ Yes | ✅ Yes |

---

## 🎓 Summary

**Quick Decision Guide:**

```
Are you debugging? 
├─ YES → Use PLAYWRIGHT_HEADLESS=false
└─ NO → Use PLAYWRIGHT_HEADLESS=true
```

**Default Recommendations:**
- 🐳 **Docker**: `PLAYWRIGHT_HEADLESS=true`
- 💻 **Local Dev**: Your choice! Try both.
- 🏭 **Production**: `PLAYWRIGHT_HEADLESS=true`
- 🐛 **Debugging**: `PLAYWRIGHT_HEADLESS=false`

---

**Need more help?** Check [QUICK_START.md](QUICK_START.md) or [DOCKER.md](DOCKER.md)

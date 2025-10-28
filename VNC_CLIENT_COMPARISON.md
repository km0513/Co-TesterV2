# VNC Client Comparison - 100% Free Options

## Quick Recommendation

**For Co-Tester users, we recommend TigerVNC** - it's completely free, open source, and works great!

---

## Free VNC Clients Comparison

### 🥇 TigerVNC (RECOMMENDED)

**Download**: https://github.com/TigerVNC/tigervnc/releases

**Pros**:
- ✅ 100% free and open source (GPL license)
- ✅ No restrictions - personal, commercial, any use
- ✅ Lightweight (~5MB download)
- ✅ Fast performance
- ✅ Cross-platform (Windows, Mac, Linux)
- ✅ Actively maintained
- ✅ No account required
- ✅ No ads or nag screens

**Cons**:
- Basic UI (but does everything you need)

**Best for**: Everyone! Especially if you want truly free software

**Windows Installation**:
1. Download `vncviewer64-1.13.1.exe` (or latest version)
2. Run the .exe file (portable, no installation needed!)
3. Connect to `localhost:5900`
4. Enter password: `cotester`

---

### 🥈 TightVNC Viewer

**Download**: https://www.tightvnc.com/download.php

**Pros**:
- ✅ 100% free (personal and commercial use)
- ✅ Very small download (~2MB)
- ✅ Fast and efficient
- ✅ No registration required
- ✅ Windows optimized
- ✅ Simple interface

**Cons**:
- Windows only (separate version for server)
- Less frequently updated

**Best for**: Windows users who want the smallest download

**Windows Installation**:
1. Download "TightVNC Viewer" (not the full package)
2. Install or use portable version
3. Launch TightVNC Viewer
4. Connect to `localhost:5900`
5. Enter password: `cotester`

---

### 🥉 RealVNC Viewer

**Download**: https://www.realvnc.com/en/connect/download/viewer/

**Pros**:
- ✅ Free for personal/non-commercial use
- ✅ Modern, polished interface
- ✅ Feature-rich (quality settings, scaling, etc.)
- ✅ Cross-platform
- ✅ Well-documented
- ✅ Professional support available

**Cons**:
- ⚠️ Requires account creation (free)
- ⚠️ Commercial use requires license (~$40/year)
- ⚠️ Larger download (~10MB)
- ⚠️ May prompt for upgrades

**Best for**: Users who want a polished UI and don't mind creating an account

**Windows Installation**:
1. Download RealVNC Viewer
2. Install (requires account signup)
3. Open VNC Viewer app
4. Connect to `localhost:5900`
5. Enter password: `cotester`

---

## Feature Comparison

| Feature | TigerVNC | TightVNC | RealVNC Viewer |
|---------|----------|----------|----------------|
| **License** | GPL (Open Source) | GPLv2 (Open Source) | Proprietary (Free tier) |
| **Cost** | FREE ✅ | FREE ✅ | Free for personal ✅ |
| **Commercial Use** | FREE ✅ | FREE ✅ | Paid 💵 |
| **Size** | ~5MB | ~2MB | ~10MB |
| **Account Required** | NO ✅ | NO ✅ | YES ⚠️ |
| **Cross-platform** | Yes ✅ | Windows only | Yes ✅ |
| **Performance** | Excellent ⚡⚡⚡ | Excellent ⚡⚡⚡ | Good ⚡⚡ |
| **UI Quality** | Basic | Basic | Modern |
| **Updates** | Active | Occasional | Frequent |
| **Ads/Nags** | NONE ✅ | NONE ✅ | Some upgrade prompts |

---

## Installation Steps for TigerVNC (Recommended)

### Windows:
1. Go to: https://github.com/TigerVNC/tigervnc/releases
2. Download: `vncviewer64-1.13.1.exe` (or latest 64-bit version)
3. **No installation needed** - just run the .exe file!
4. In the VNC Viewer window:
   - VNC Server: `localhost:5900`
   - Click "Connect"
5. Enter password: `cotester`
6. Done! You'll see the Docker container's display

### Mac:
1. Download: `TigerVNC-1.13.1.dmg` (or latest)
2. Open the DMG and drag to Applications
3. Run TigerVNC Viewer
4. Connect to `localhost:5900`
5. Password: `cotester`

### Linux:
```bash
# Ubuntu/Debian
sudo apt install tigervnc-viewer

# Fedora/RHEL
sudo dnf install tigervnc

# Run
vncviewer localhost:5900
```

---

## Quick Start Command

After installing any VNC viewer, run your Docker container with:

```powershell
docker run -p 5000:5000 -p 5900:5900 --env-file .env -e ENABLE_VNC=true -e PLAYWRIGHT_HEADLESS=false kishore1305/co-tester:vnc
```

Then connect your VNC viewer to `localhost:5900` with password `cotester`.

---

## Troubleshooting

### "Connection refused"
- **Check**: Is Docker container running with VNC enabled?
  ```powershell
  docker logs cotester-vnc | findstr VNC
  # Should show: "VNC server started on port 5900"
  ```
- **Check**: Did you expose port 5900? `-p 5900:5900`

### "Authentication failed"
- **Default password**: `cotester`
- **Custom password**: Set with `-e VNC_PASSWORD=YourPassword` when running Docker

### "Screen is blank"
- **Wait**: 10-15 seconds after container starts
- **Check**: Xvfb and fluxbox running:
  ```powershell
  docker exec cotester-vnc ps aux | findstr -E "Xvfb|fluxbox"
  ```

### "Can't see browser window"
- **Check**: Is `PLAYWRIGHT_HEADLESS=false`?
- **Check**: Using VNC image? `docker ps` should show `:vnc` tag
- **Try**: Close and reconnect VNC viewer

---

## Why We Recommend TigerVNC

1. **No Strings Attached**: Truly free for any use (personal, commercial, enterprise)
2. **Open Source**: You can see exactly what it does (security!)
3. **No Account**: Just download and run
4. **Small & Fast**: Only 5MB, launches instantly
5. **No Nags**: No upgrade prompts or ads
6. **Active Development**: Regular updates and bug fixes
7. **Works Everywhere**: Same experience on Windows, Mac, Linux

**Bottom Line**: For Co-Tester, you just need to see the browser in Docker. TigerVNC does this perfectly with zero hassle and zero cost! 🎯

---

## Summary Table

| If you want... | Choose... |
|----------------|-----------|
| Truly free for any use | **TigerVNC** ✅ |
| Smallest download | **TightVNC** |
| Modern UI & features | **RealVNC Viewer** (with account) |
| No account signup | **TigerVNC** or **TightVNC** ✅ |
| Commercial use | **TigerVNC** or **TightVNC** ✅ |
| Mac/Linux support | **TigerVNC** ✅ |
| **Our recommendation** | **TigerVNC** 🥇 |

---

## Download Links

### TigerVNC (Recommended)
- **All platforms**: https://github.com/TigerVNC/tigervnc/releases
- **Direct Windows 64-bit**: https://github.com/TigerVNC/tigervnc/releases/download/v1.13.1/vncviewer64-1.13.1.exe

### TightVNC
- **Windows**: https://www.tightvnc.com/download.php
- Choose "Installer for Windows (ZIP archive)" or "TightVNC Viewer only"

### RealVNC Viewer
- **All platforms**: https://www.realvnc.com/en/connect/download/viewer/
- Requires free account creation

---

**Note**: All three options work perfectly with Co-Tester's VNC image. The choice is yours based on preferences! 🚀

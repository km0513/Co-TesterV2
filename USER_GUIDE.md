# 📦 Co-Tester - User Installation Guide

## 🎯 What is Co-Tester?

Co-Tester is a comprehensive testing automation platform that helps you:
- 🤖 Generate test cases with AI
- 🎭 Record and replay browser interactions
- 🔌 Test REST and GraphQL APIs
- 📋 Integrate seamlessly with Jira
- 📊 Create detailed test reports

## 📋 Before You Start

You need:
1. **Docker Desktop** installed on your computer
   - Windows/Mac: [Download Docker Desktop](https://www.docker.com/products/docker-desktop)
   - Linux: [Install Docker Engine](https://docs.docker.com/engine/install/)

2. **A Google Gemini API Key** (free)
   - Get it here: https://ai.google.dev/
   - Takes 2 minutes to create

## 🚀 Installation (First Time)

### Step 1: Create a Folder

Create a folder where Co-Tester will store its data:

**Windows:**
```powershell
mkdir C:\co-tester
cd C:\co-tester
```

**Mac/Linux:**
```bash
mkdir ~/co-tester
cd ~/co-tester
```

### Step 2: Download Setup Files

Download these 2 files to your co-tester folder:
1. `docker-compose.yml` - [Download](link-to-file)
2. `.env.docker.example` - [Download](link-to-file)

### Step 3: Configure Your Settings

Rename `.env.docker.example` to `.env` and edit it:

**Windows:** Right-click → Edit with Notepad  
**Mac/Linux:** `nano .env`

**Required settings:**
```env
SECRET_KEY=put-any-random-long-string-here-min-32-characters
GOOGLE_API_KEY=your-google-gemini-api-key-from-step-2
GOOGLE_API_MODEL=gemini-2.0-flash-exp
```

**Optional settings (for Jira integration):**
```env
JIRA_CLIENT_ID=your-jira-client-id
JIRA_CLIENT_SECRET=your-jira-client-secret
```

💡 **Tip:** To generate a random SECRET_KEY:
- Windows: Use any password generator online
- Mac/Linux: Run `openssl rand -hex 32`

### Step 4: Start Co-Tester

**Open Command Prompt/Terminal** in your co-tester folder and run:

```bash
docker-compose up -d
```

This will:
- ✅ Download Co-Tester (first time only, ~2GB)
- ✅ Install all dependencies automatically
- ✅ Start the application

### Step 5: Open Co-Tester

1. Open your web browser
2. Go to: **http://localhost:5000**
3. Start testing! 🎉

## 🔄 Updating Co-Tester

When a new version is released, updating is simple:

### Windows:
1. Double-click `update.bat`
2. Wait for update to complete
3. Done! ✅

### Mac/Linux:
```bash
./update.sh
```

**OR manually:**
```bash
docker-compose pull
docker-compose up -d
```

Your data (tests, reports, settings) is **automatically preserved** during updates! 🛡️

## 📁 Your Data

Co-Tester stores all your data in the `data` folder:

```
co-tester/
├── docker-compose.yml
├── .env
└── data/
    ├── instance/      ← Database
    ├── uploads/       ← Uploaded files
    ├── reports/       ← Test reports
    └── playwright-output/  ← Recorded tests
```

**💡 Backup Tip:** To backup everything, just copy the `data` folder!

## 🛠️ Common Tasks

### Starting Co-Tester:
```bash
docker-compose start
```

### Stopping Co-Tester:
```bash
docker-compose stop
```

### Restarting Co-Tester:
```bash
docker-compose restart
```

### Viewing Logs (troubleshooting):
```bash
docker-compose logs -f
```
Press `Ctrl+C` to stop viewing logs.

### Checking if Co-Tester is Running:
```bash
docker-compose ps
```

Should show: `Status: Up`

## 🔧 Troubleshooting

### Problem: "Port 5000 is already in use"

**Solution:** Change the port in `docker-compose.yml`

Change this line:
```yaml
ports:
  - "5000:5000"
```

To (for example, port 8080):
```yaml
ports:
  - "8080:5000"
```

Then access at: http://localhost:8080

---

### Problem: "Cannot connect to Docker daemon"

**Solution:** Make sure Docker Desktop is running
- Windows: Check system tray for Docker icon
- Mac: Check menu bar for Docker icon
- Linux: Run `sudo systemctl start docker`

---

### Problem: Co-Tester won't start

**Check logs:**
```bash
docker-compose logs
```

**Common causes:**
1. Missing `.env` file → Create it from `.env.docker.example`
2. Invalid API key → Check your Google API key
3. Port conflict → Change port (see above)

---

### Problem: "Updates not working"

**Solution:** Full reinstall (keeps your data):
```bash
docker-compose down
docker-compose pull
docker-compose up -d
```

---

### Problem: Want to start fresh (delete all data)

**⚠️ WARNING: This deletes everything!**

```bash
# Stop Co-Tester
docker-compose down

# Delete all data
rm -rf data/        # Mac/Linux
rmdir /s data       # Windows

# Start fresh
docker-compose up -d
```

## 🌐 Accessing from Other Devices

To access Co-Tester from other computers on your network:

1. Find your computer's IP address:
   - Windows: `ipconfig` (look for IPv4 Address)
   - Mac: System Preferences → Network
   - Linux: `ip addr`

2. On another device, go to:
   ```
   http://YOUR-IP-ADDRESS:5000
   ```
   Example: `http://192.168.1.100:5000`

3. **Firewall:** You may need to allow port 5000 through your firewall.

## 💡 Pro Tips

1. **Bookmark it:** Add http://localhost:5000 to your browser favorites

2. **Desktop shortcut:** Create a shortcut that opens the URL automatically

3. **Auto-start:** Configure Docker Desktop to start on system boot
   - Docker Desktop → Settings → General → "Start Docker Desktop when you log in"

4. **Regular backups:** Copy the `data` folder weekly to a safe location

5. **Check for updates:** Join our mailing list for update notifications

## 📞 Getting Help

- **Documentation:** See `DOCKER.md` for advanced topics
- **Issues:** Report bugs on GitHub
- **Questions:** Check the FAQ section

## 📝 Quick Reference

| Command | What it does |
|---------|--------------|
| `docker-compose up -d` | Start Co-Tester |
| `docker-compose stop` | Stop Co-Tester |
| `docker-compose restart` | Restart Co-Tester |
| `docker-compose pull` | Download updates |
| `docker-compose logs -f` | View live logs |
| `docker-compose ps` | Check status |

---

**Happy Testing! 🚀**

Need help? Open an issue on GitHub or check the documentation.
